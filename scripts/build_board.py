#!/usr/bin/env python3
"""Build a local card table; never print the browser's fixed-deck payload."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid
import zlib

import tarot_deck as engine


def data_uri(path):
    if not path.is_file() or path.is_symlink() or path.suffix != ".webp":
        raise ValueError("经典维特牌图尚未完整准备好")
    content = path.read_bytes()
    if len(content) < 16 or content[:4] != b"RIFF" or content[8:12] != b"WEBP":
        raise ValueError("经典维特牌图格式不正确")
    return "data:image/webp;base64," + base64.b64encode(content).decode("ascii")


def make_config(state, session, theme, artwork):
    engine.validate(state)
    public = engine.public_status(state)
    metadata = engine.clarifier_metadata(state)
    latest_round = metadata["clarifier_round"]
    round_start = metadata["clarifier_rounds"][-1]["start_position_index"] - 1 if latest_round else 0
    drawn_numbers = [card["number"] for card in public["drawn"]]
    round_id = state["session_id"] + ":round:" + str(latest_round)
    view_seed = [round_id, drawn_numbers, public["cards_still_needed"]]
    view_id = hashlib.sha256(engine.canonical(view_seed).encode("utf-8")).hexdigest()[:24]
    catalog = {
        card_id: {"name": names["name"], "image": data_uri(artwork / (card_id + ".webp"))}
        for card_id, names in engine.CATALOG.items()
    }
    # Catalog order is canonical. Only this packet maps hidden slots to cards.
    # It prevents accidental disclosure, and is deliberately not encryption.
    private_deck = [[card["card_id"], 1 if card["orientation"] == "reversed" else 0] for card in state["cards"]]
    raw = json.dumps(private_deck, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    opaque = {"encoding": "deflate-base64", "data": base64.b64encode(zlib.compress(raw, 9)).decode("ascii"), "fallback": base64.b64encode(raw).decode("ascii")}
    def visible_card(card):
        return {"slot": card["number"], "card_id": card["card_id"], "reversed": card["orientation"] == "reversed"}
    return {
        "version": 2, "session_id": state["session_id"], "session_filename": session.name,
        "commitment": state["commitment"], "round_id": round_id, "view_id": view_id,
        "clarifier_round": latest_round, "status": state["status"], "spread": state["spread"],
        "orientation_mode": state["orientation_mode"], "needed": public["cards_still_needed"],
        "drawn_slots": drawn_numbers, "available_slots": public["remaining_numbers"],
        "current_round_slots": drawn_numbers[round_start:],
        "previous_cards": [visible_card(card) for card in public["drawn"][:round_start]],
        "completed_cards": [visible_card(card) for card in public["drawn"][round_start:]] if state["status"] == "complete" else [],
        "theme_label": theme.strip()[:100], "catalog": catalog,
        "back_image": data_uri(artwork / "back.webp"), "deck_payload": opaque,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--theme-label", default="未指定")
    args = parser.parse_args()
    try:
        if not args.session.is_absolute() or not args.output.is_absolute():
            raise ValueError("场次和输出文件都需要绝对路径")
        if args.session.is_symlink():
            raise ValueError("场次文件不能是符号链接")
        session, output = args.session.resolve(), args.output.resolve()
        if output == session or (output.exists() and session.exists() and os.path.samefile(output, session)):
            raise ValueError("抽牌界面不能覆盖场次文件")
        if output.suffix.lower() != ".html":
            raise ValueError("抽牌界面需要保存为 .html 文件")
        skill_dir = Path(__file__).resolve().parent.parent
        with engine.locked(session):
            config = make_config(engine.load_state(session), session, args.theme_label, skill_dir / "assets" / "artwork")
        payload = json.dumps(config, ensure_ascii=False, separators=(",", ":"))
        for char, replacement in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
            payload = payload.replace(char, replacement)
        template = (skill_dir / "assets" / "card-table.html").read_text(encoding="utf-8")
        if template.count("__TAROT_PUBLIC_CONFIG__") != 1:
            raise ValueError("抽牌界面模板不完整")
        fragment = template.replace("__BOARD_ID__", uuid.uuid4().hex[:16]).replace("__TAROT_PUBLIC_CONFIG__", payload)
        encoded = fragment.encode("utf-8")
        if len(encoded) >= 1_000_000:
            raise ValueError("牌图过大，请压缩整套 WebP 牌图")
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=output.parent, prefix=".tarot-board-", suffix=".html", delete=False) as handle:
                temp_name = handle.name
                handle.write(encoded)
            os.replace(temp_name, output)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
        print(json.dumps({"output": str(output), "session_id": config["session_id"], "round_id": config["round_id"], "view_id": config["view_id"], "cards_still_needed": config["needed"], "bytes": len(encoded)}, ensure_ascii=False))
    except (OSError, ValueError, engine.TarotError):
        print(json.dumps({"error": "无法生成抽牌桌，请核对完整牌图、场次、输出路径与文件大小；未输出或改动隐藏牌序。"}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
