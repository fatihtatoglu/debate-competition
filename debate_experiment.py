import json
import os
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

from nanoid import generate
from openai import OpenAI
from dotenv import load_dotenv

OUTPUT_DIR = Path("outputs")
PROMPT_DIR = Path("prompts")

TEMPERATURE = 0.7

LANG = "en"

OUTPUT_DIR.mkdir(exist_ok=True)

def get_api_key() -> str:
    return os.getenv("API_KEY") or os.getenv("API_KEY", "")


def require_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Missing required env var: {key}")
    return value


def resolve_backend(role: str) -> Dict[str, object]:
    backend = require_env(f"{role}_BACKEND").strip().lower()
    if backend not in {"local", "online"}:
        raise ValueError(f"{role}_BACKEND must be 'local' or 'online'.")

    base_url = require_env(
        "LOCAL_BASE_URL" if backend == "local" else "ONLINE_BASE_URL"
    )
    model_name = require_env(f"{role}_MODEL")

    return {
        "backend": backend,
        "base_url": base_url,
        "model": model_name,
        "requires_api_key": backend == "online",
    }


def build_client(base_url: str, requires_api_key: bool) -> OpenAI:
    api_key = get_api_key()
    if requires_api_key and not api_key:
        raise ValueError(
            "API key is required for online backends. Set API_KEY or OPENAI_API_KEY."
        )
    return OpenAI(base_url=base_url, api_key=api_key or "no-need-api-key")


def parse_list_env(key: str) -> List[str]:
    return [item.strip() for item in require_env(key).split(",") if item.strip()]


def build_judge_configs() -> List[Dict[str, object]]:
    models = parse_list_env("JUDGE_MODELS")
    backends = parse_list_env("JUDGE_BACKENDS")
    if len(models) != len(backends):
        raise ValueError("JUDGE_MODELS and JUDGE_BACKENDS must have the same length.")

    configs = []
    for model, backend in zip(models, backends):
        if backend not in {"local", "online"}:
            raise ValueError("JUDGE_BACKENDS values must be 'local' or 'online'.")
        base_url = require_env(
            "LOCAL_BASE_URL" if backend == "local" else "ONLINE_BASE_URL"
        )
        configs.append({
            "model": model,
            "backend": backend,
            "base_url": base_url,
            "requires_api_key": backend == "online",
        })
    return configs

def log(message: str) -> None:
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp} UTC] {message}")


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def render_prompt(template: str, variables: Dict[str, str]) -> str:
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{{{key}}}}}", value)
    return result


def call_model(client: OpenAI, model: str, messages: List[Dict]) -> Dict:
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=TEMPERATURE,
    )
    return {
        "model": model,
        "content": response.choices[0].message.content,
        "usage": response.usage.model_dump() if response.usage else None,
    }


def save_jsonl(records: List[Dict], filename: Path):
    with filename.open("a+", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def merge_responses(history: List[Dict]) -> str:
    return "\n\n".join(
        f"Round {i+1}:\n{item['content']}"
        for i, item in enumerate(history)
    )


def build_opponent_variables(
    round_index: int,
    opponent_history: List[Dict],
    opponent_label: str,
) -> Dict[str, str]:
    if round_index <= 1:
        return {}
    target_index = round_index - 2
    if target_index >= len(opponent_history):
        return {}
    key = f"{opponent_label}_ROUND_{round_index - 1}"
    return {key: opponent_history[target_index]["content"]}


def unique_id(seen: set) -> str:
    while True:
        uid = generate(size=16, alphabet="0123456789abcdefghijklmnopqrstuvwxyz")
        if uid not in seen:
            seen.add(uid)
            return uid


def extract_usage_fields(usage: Dict) -> Tuple[float, int, int, int, str, int]:
    if not usage:
        return 0.0, 0, 0, 0, "", 0
    cost = usage.get("total_cost")
    if cost is None:
        cost = usage.get("cost", 0.0)
    return (
        float(cost or 0.0),
        int(usage.get("completion_tokens") or 0),
        int(usage.get("prompt_tokens") or 0),
        int(usage.get("total_tokens") or 0),
        "",
        int(usage.get("reasoning_tokens") or 0),
    )


def parse_jury_response(text: str) -> Dict:
    if not text:
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].lstrip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}


def run_jury_evaluation(
    client: OpenAI,
    judge_model: str,
    topic: str,
    conditions: str,
    history_a: List[Dict],
    history_b: List[Dict],
    blind: bool,
):
    judge_template = load_prompt("judge/judge_evaluation.txt")
    log("Running jury evaluation.")

    side_a_text = merge_responses(history_a)
    side_b_text = merge_responses(history_b)
    side_map = {"A": "A", "B": "B"}
    if blind:
        side_a_text, side_b_text = side_b_text, side_a_text
        side_map = {"A": "B", "B": "A"}

    rendered_prompt = render_prompt(
        judge_template,
        {
            "TOPIC": topic,
            "CONDITIONS": conditions,
            "SIDE_A_TEXT": side_a_text,
            "SIDE_B_TEXT": side_b_text,
        },
    )

    messages = [
        {"role": "system", "content": "You are a neutral debate judge."},
        {"role": "user", "content": rendered_prompt},
    ]

    result = call_model(client, judge_model, messages)

    return {
        "judge_model": judge_model,
        "side_map": side_map,
        "prompt": rendered_prompt,
        "raw_response": result["content"],
        "usage": result["usage"],
    }


def remap_winner(raw_winner: str, side_map: Dict[str, str]) -> str:
    if raw_winner == "Side A":
        return "Side " + side_map["A"]
    if raw_winner == "Side B":
        return "Side " + side_map["B"]
    return raw_winner or ""


def normalize_jury_scores(parsed: Dict, side_map: Dict[str, str]) -> Dict:
    if side_map.get("A") == "A":
        return parsed
    return {
        "total_score_A": parsed.get("total_score_B"),
        "total_score_B": parsed.get("total_score_A"),
        "detailed_scores_A": parsed.get("detailed_scores_B"),
        "detailed_scores_B": parsed.get("detailed_scores_A"),
        "winner": parsed.get("winner"),
        "reasoning": parsed.get("reasoning"),
        "general": parsed.get("general"),
    }


def is_valid_jury(parsed: Dict) -> bool:
    if not parsed:
        return False
    if parsed.get("winner") not in {"Side A", "Side B"}:
        return False
    return (
        parsed.get("total_score_A") is not None
        and parsed.get("total_score_B") is not None
    )
def run_debate(
    client_a: OpenAI,
    client_b: OpenAI,
    judge_configs: List[Dict[str, object]],
    model_a: str,
    model_b: str,
    topic: str,
    conditions: str,
    blind_jury: bool,
):
    rounds = [
        "round1_opening.txt",
        "round2_rebuttal.txt",
        "round3_assumptions.txt",
        "round4_closing.txt",
    ]

    start_time = time.time()
    log(f"Debate started with topic: {topic}")
    log(
        "Models: "
        f"A={model_a}, "
        f"B={model_b}, "
        f"Judge={','.join(cfg['model'] for cfg in judge_configs)}"
    )

    history_a = []
    history_b = []
    messages_a = []
    messages_b = []
    rounds_log = []
    total_cost = 0.0
    total_completion_tokens = 0
    total_prompt_tokens = 0
    total_tokens = 0
    total_reasoning_tokens = 0

    system_prompt = load_prompt("system.txt")
    messages_a.append({"role": "system", "content": system_prompt})
    messages_b.append({"role": "system", "content": system_prompt})

    for i, round_file in enumerate(rounds, start=1):
        round_template_a = load_prompt(f"model_a/{round_file}")
        round_template_b = load_prompt(f"model_b/{round_file}")

        log(f"Round {i} started: {round_file}")

        variables_a = {"TOPIC": topic, "CONDITIONS": conditions}
        variables_a.update(build_opponent_variables(i, history_b, "MODEL_B"))
        prompt_a = render_prompt(round_template_a, variables_a)
        messages_a.append({"role": "user", "content": prompt_a})
        log(f"Calling model A for round {i}.")
        round_start_a = time.time()
        result_a = call_model(client_a, model_a, messages_a)
        round_duration_a = time.time() - round_start_a
        log(f"Model A completed round {i}.")
        history_a.append(result_a)
        messages_a.append({"role": "assistant", "content": result_a.get("content") or ""})

        (
            cost_a,
            completion_tokens_a,
            prompt_tokens_a,
            total_tokens_a,
            reasoning_a,
            reasoning_tokens_a,
        ) = extract_usage_fields(result_a.get("usage"))
        rounds_log.append({
            "id": i,
            "side": "A",
            "prompt": prompt_a,
            "content": result_a.get("content") or "",
            "cost": cost_a,
            "completion_tokens": completion_tokens_a,
            "prompt_tokens": prompt_tokens_a,
            "total_tokens": total_tokens_a,
            "reasoning": reasoning_a,
            "reasoning_tokens": reasoning_tokens_a,
            "duration_seconds": round_duration_a,
        })
        total_cost += cost_a
        total_completion_tokens += completion_tokens_a
        total_prompt_tokens += prompt_tokens_a
        total_tokens += total_tokens_a
        total_reasoning_tokens += reasoning_tokens_a

        time.sleep(1)

        variables_b = {"TOPIC": topic, "CONDITIONS": conditions}
        variables_b.update(build_opponent_variables(i, history_a, "MODEL_A"))
        prompt_b = render_prompt(round_template_b, variables_b)
        messages_b.append({"role": "user", "content": prompt_b})
        log(f"Calling model B for round {i}.")
        round_start_b = time.time()
        result_b = call_model(client_b, model_b, messages_b)
        round_duration_b = time.time() - round_start_b
        log(f"Model B completed round {i}.")
        history_b.append(result_b)
        messages_b.append({"role": "assistant", "content": result_b.get("content") or ""})

        (
            cost_b,
            completion_tokens_b,
            prompt_tokens_b,
            total_tokens_b,
            reasoning_b,
            reasoning_tokens_b,
        ) = extract_usage_fields(result_b.get("usage"))
        rounds_log.append({
            "id": i,
            "side": "B",
            "prompt": prompt_b,
            "content": result_b.get("content") or "",
            "cost": cost_b,
            "completion_tokens": completion_tokens_b,
            "prompt_tokens": prompt_tokens_b,
            "total_tokens": total_tokens_b,
            "reasoning": reasoning_b,
            "reasoning_tokens": reasoning_tokens_b,
            "duration_seconds": round_duration_b,
        })
        total_cost += cost_b
        total_completion_tokens += completion_tokens_b
        total_prompt_tokens += prompt_tokens_b
        total_tokens += total_tokens_b
        total_reasoning_tokens += reasoning_tokens_b

        time.sleep(1)

    jury_results = []
    jury_parsed_list = []
    for cfg in judge_configs:
        jury_result = run_jury_evaluation(
            client=cfg["client"],
            judge_model=cfg["model"],
            topic=topic,
            conditions=conditions,
            history_a=history_a,
            history_b=history_b,
            blind=blind_jury,
        )
        (
            jury_cost,
            jury_completion_tokens,
            jury_prompt_tokens,
            jury_total_tokens,
            jury_reasoning,
            jury_reasoning_tokens,
        ) = extract_usage_fields(jury_result.get("usage"))
        total_cost += jury_cost
        total_completion_tokens += jury_completion_tokens
        total_prompt_tokens += jury_prompt_tokens
        total_tokens += jury_total_tokens
        total_reasoning_tokens += jury_reasoning_tokens

        jury_parsed_raw = parse_jury_response(jury_result.get("raw_response") or "")
        remapped_winner = remap_winner(
            jury_parsed_raw.get("winner", ""),
            jury_result.get("side_map", {"A": "A", "B": "B"}),
        )
        jury_parsed_raw["winner"] = remapped_winner
        jury_parsed = normalize_jury_scores(
            jury_parsed_raw,
            jury_result.get("side_map", {"A": "A", "B": "B"}),
        )
        if not is_valid_jury(jury_parsed):
            log(f"Skipping invalid jury output for model {cfg['model']}.")
            continue

        jury_results.append({
            "model": cfg["model"],
            "prompt": jury_result.get("prompt") or "",
            "content": jury_result.get("raw_response") or "",
            "cost": jury_cost,
            "completion_tokens": jury_completion_tokens,
            "prompt_tokens": jury_prompt_tokens,
            "total_tokens": jury_total_tokens,
            "reasoning": jury_reasoning,
            "reasoning_tokens": jury_reasoning_tokens,
            "blind": blind_jury,
            "side_map": jury_result.get("side_map", {"A": "A", "B": "B"}),
        })
        jury_parsed_list.append(jury_parsed)

    total_duration_seconds = time.time() - start_time

    winners = [item.get("winner") for item in jury_parsed_list if item.get("winner")]
    winner_counts = {"Side A": winners.count("Side A"), "Side B": winners.count("Side B")}
    final_winner = ""
    if winners:
        final_winner = (
            "Side A" if winner_counts["Side A"] >= winner_counts["Side B"] else "Side B"
        )
    winner_reason = ""
    general_summary = ""
    for parsed in jury_parsed_list:
        if parsed.get("winner") == final_winner:
            winner_reason = parsed.get("reasoning", "") or winner_reason
            general_summary = parsed.get("general", "") or general_summary
            break

    evaluation = {
        "juries": jury_results,
        "parsed": jury_parsed_list,
        "winner_counts": winner_counts,
    }

    output_file = OUTPUT_DIR / "out.jsonl"

    seen_ids = set()
    record = {
        "id": unique_id(seen_ids),
        "topic": topic,
        "conditions": conditions,
        "lang": LANG,
        "proposition": model_a,
        "opposition": model_b,
        "jury": ",".join(cfg["model"] for cfg in judge_configs),
        "rounds": rounds_log,
        "evaluation": evaluation,
        "result": {
            "general": general_summary,
            "winner": final_winner,
            "winning_reason": winner_reason,
        },
        "total_cost": total_cost,
        "total_completion_tokens": total_completion_tokens,
        "total_prompt_tokens": total_prompt_tokens,
        "total_tokens": total_tokens,
        "total_reasoning_tokens": total_reasoning_tokens,
        "total_duration_seconds": total_duration_seconds,
    }
    save_jsonl([record], output_file)

    log(f"Debate finished. Output saved to {output_file}")


if __name__ == "__main__":
    load_dotenv()

    topic = require_env("TOPIC")
    conditions = os.getenv("CONDITIONS", "").strip()
    model_a_config = resolve_backend("MODEL_A")
    model_b_config = resolve_backend("MODEL_B")
    judge_configs = build_judge_configs()
    blind_jury = os.getenv("JUDGE_BLIND", "true").strip().lower() == "true"

    client_a = build_client(
        model_a_config["base_url"],
        model_a_config["requires_api_key"],
    )
    client_b = build_client(
        model_b_config["base_url"],
        model_b_config["requires_api_key"],
    )
    judge_clients = {}
    for cfg in judge_configs:
        key = (cfg["base_url"], cfg["requires_api_key"])
        if key not in judge_clients:
            judge_clients[key] = build_client(
                cfg["base_url"],
                cfg["requires_api_key"],
            )
        cfg["client"] = judge_clients[key]

    log(
        "Backends: "
        f"A={model_a_config['backend']} "
        f"B={model_b_config['backend']} "
        f"Judge={','.join(cfg['backend'] for cfg in judge_configs)}"
    )
    log(
        "Base URLs: "
        f"A={model_a_config['base_url']} "
        f"B={model_b_config['base_url']} "
        f"Judge={','.join(cfg['base_url'] for cfg in judge_configs)}"
    )

    run_debate(
        client_a,
        client_b,
        judge_configs,
        model_a_config["model"],
        model_b_config["model"],
        topic,
        conditions,
        blind_jury,
    )
