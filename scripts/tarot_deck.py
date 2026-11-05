#!/usr/bin/env python3
"""A local, fixed-position Rider–Waite–Smith deck. Python standard library only."""

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
import uuid


DECK = "Rider–Waite–Smith (78 cards)"
VERSION = 1
MAJORS = [
    ("愚人", "The Fool"), ("魔术师", "The Magician"),
    ("女祭司", "The High Priestess"), ("皇后", "The Empress"),
    ("皇帝", "The Emperor"), ("教皇", "The Hierophant"),
    ("恋人", "The Lovers"), ("战车", "The Chariot"),
    ("力量", "Strength"), ("隐者", "The Hermit"),
    ("命运之轮", "Wheel of Fortune"), ("正义", "Justice"),
    ("倒吊人", "The Hanged Man"), ("死神", "Death"),
    ("节制", "Temperance"), ("恶魔", "The Devil"),
    ("高塔", "The Tower"), ("星星", "The Star"),
    ("月亮", "The Moon"), ("太阳", "The Sun"),
    ("审判", "Judgement"), ("世界", "The World"),
]
SUITS = [("wands", "权杖", "Wands"), ("cups", "圣杯", "Cups"),
         ("swords", "宝剑", "Swords"), ("pentacles", "星币", "Pentacles")]
RANKS = [("ace", "王牌", "Ace"), ("02", "二", "Two"),
         ("03", "三", "Three"), ("04", "四", "Four"),
         ("05", "五", "Five"), ("06", "六", "Six"),
         ("07", "七", "Seven"), ("08", "八", "Eight"),
         ("09", "九", "Nine"), ("10", "十", "Ten"),
         ("page", "侍从", "Page"), ("knight", "骑士", "Knight"),
         ("queen", "王后", "Queen"), ("king", "国王", "King")]
CATALOG = {
    **{f"major-{i:02d}": {"name": zh, "english_name": en}
       for i, (zh, en) in enumerate(MAJORS)},
    **{f"{suit}-{rank}": {"name": zh_suit + zh_rank,
                          "english_name": en_rank + " of " + en_suit}
       for suit, zh_suit, en_suit in SUITS
       for rank, zh_rank, en_rank in RANKS},
}


class TarotError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise TarotError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def commitment_payload(state):
    return {"deck": DECK, "cards": state["cards"], "nonce": state["nonce"]}


def digest(state):
    return hashlib.sha256(canonical(commitment_payload(state)).encode("utf-8")).hexdigest()


def positions_for(spread, choices):
    if spread == "general":
        if choices is not None:
            raise TarotError("general 牌阵不接受 --choices。")
        return ["当前状态", "主要影响", "行动建议"]
    if spread != "choice" or type(choices) is not int or not 2 <= choices <= 38:
        raise TarotError("choice 牌阵需要 --choices 2..38（共 1 + 2N 张牌）。")
    positions = ["当前状态"]
    for index in range(choices):
        label = chr(65 + index) if index < 26 else str(index + 1)
        positions.extend([f"选项{label}的推进动力", f"选项{label}的阻力或代价"])
    return positions


def clarifier_positions(round_number, count):
    return [f"第{round_number}轮补充澄清·第{index}张" for index in range(1, count + 1)]


def clarifier_metadata(state):
    """Legacy version-1 sessions gain metadata only when clarify writes them."""
    return {
        "base_positions_count": state.get("base_positions_count", len(positions_for(state["spread"], state["choices"]))),
        "clarifier_round": state.get("clarifier_round", 0),
        "clarifier_rounds": state.get("clarifier_rounds", []),
    }


def validate(state):
    """Reject incomplete/corrupted state before any mutation or public disclosure."""
    try:
        if type(state) is not dict or type(state["version"]) is not int or state["version"] != VERSION:
            raise ValueError()
        if str(uuid.UUID(state["session_id"])) != state["session_id"]:
            raise ValueError()
        if state["deck"] != DECK or type(state["total_cards"]) is not int or state["total_cards"] != 78:
            raise ValueError()
        if type(state["created_at"]) is not str:
            raise ValueError()
        datetime.datetime.fromisoformat(state["created_at"])
        if state["orientation_mode"] not in ("mixed", "upright-only"):
            raise ValueError()
        expected_positions = positions_for(state["spread"], state["choices"])
        metadata_keys = {"base_positions_count", "clarifier_round", "clarifier_rounds"}
        rounds = []
        if metadata_keys.intersection(state):
            # Optional as a group for old v1 files; partial metadata is corruption.
            if not metadata_keys.issubset(state):
                raise ValueError()
            if type(state["base_positions_count"]) is not int or state["base_positions_count"] != len(expected_positions):
                raise ValueError()
            rounds = state["clarifier_rounds"]
            if type(rounds) is not list or type(state["clarifier_round"]) is not int or state["clarifier_round"] != len(rounds):
                raise ValueError()
            for round_number, item in enumerate(rounds, 1):
                if type(item) is not dict or set(item) != {"round", "start_position_index", "count"}:
                    raise ValueError()
                if any(type(item[key]) is not int for key in item):
                    raise ValueError()
                if item["round"] != round_number or item["start_position_index"] != len(expected_positions) + 1:
                    raise ValueError()
                if item["count"] < 1 or len(expected_positions) + item["count"] > 78:
                    raise ValueError()
                expected_positions.extend(clarifier_positions(round_number, item["count"]))
        if state["positions"] != expected_positions:
            raise ValueError()
        cards = state["cards"]
        if type(cards) is not list or len(cards) != 78:
            raise ValueError()
        if {card["card_id"] for card in cards} != set(CATALOG):
            raise ValueError()
        for card in cards:
            if set(card) != {"card_id", "orientation"}:
                raise ValueError()
            if card["orientation"] not in ("upright", "reversed"):
                raise ValueError()
            if state["orientation_mode"] == "upright-only" and card["orientation"] != "upright":
                raise ValueError()
        if type(state["nonce"]) is not str or len(state["nonce"]) != 64:
            raise ValueError()
        bytes.fromhex(state["nonce"])
        if state["commitment"] != digest(state):
            raise ValueError()
        drawn = state["drawn"]
        if type(drawn) is not list or len(drawn) > len(state["positions"]):
            raise ValueError()
        seen = set()
        for index, draw in enumerate(drawn):
            if type(draw) is not dict or set(draw) != {"number", "position_index"}:
                raise ValueError()
            number = draw["number"]
            if type(number) is not int or not 1 <= number <= 78 or number in seen:
                raise ValueError()
            if type(draw["position_index"]) is not int or draw["position_index"] != index + 1:
                raise ValueError()
            seen.add(number)
        if rounds and len(drawn) < rounds[-1]["start_position_index"] - 1:
            # A new round can only follow a completed base spread/previous round.
            raise ValueError()
        expected = "complete" if len(drawn) == len(state["positions"]) else "awaiting_draw"
        if state["status"] != expected:
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError, TarotError):
        raise TarotError("会话文件不完整或校验失败；未改动牌序。") from None


def public_card(card, number):
    return {"number": number, **card, **CATALOG[card["card_id"]],
            "orientation_label": "正位" if card["orientation"] == "upright" else "逆位"}


def public_status(state):
    result = {key: state[key] for key in (
        "session_id", "deck", "created_at", "status", "total_cards", "spread",
        "choices", "orientation_mode", "positions", "commitment")}
    metadata = clarifier_metadata(state)
    result.update(metadata)
    drawn_numbers = {draw["number"] for draw in state["drawn"]}
    result["drawn"] = []
    for draw in state["drawn"]:
        index = draw["position_index"]
        clarifier = next((item for item in metadata["clarifier_rounds"]
                          if item["start_position_index"] <= index < item["start_position_index"] + item["count"]), None)
        result["drawn"].append({
            **public_card(state["cards"][draw["number"] - 1], draw["number"]),
            "position_index": index, "position": state["positions"][index - 1],
            "is_clarifier": clarifier is not None,
            "clarifier_round": clarifier["round"] if clarifier else 0,
            "clarifier_index": index - clarifier["start_position_index"] + 1 if clarifier else None,
        })
    result["remaining_numbers"] = [number for number in range(1, 79) if number not in drawn_numbers]
    result["cards_still_needed"] = len(state["positions"]) - len(state["drawn"])
    return result


def session_path(value):
    path = Path(value)
    if not path.is_absolute():
        raise TarotError("--session 必须是绝对路径。")
    if path.is_symlink():
        raise TarotError("会话文件不能是符号链接。")
    return path


def make_private_parents(directory):
    if directory.exists():
        if not directory.is_dir():
            raise TarotError("会话的父路径不是目录。")
        return
    make_private_parents(directory.parent)
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        if not directory.is_dir():
            raise TarotError("会话的父路径不是目录。") from None


@contextlib.contextmanager
def locked(path, create=False):
    if create:
        make_private_parents(path.parent)
    elif not path.parent.is_dir():
        raise TarotError("找不到会话。")
    lock_path = path.with_name(path.name + ".lock")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(lock_path), flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise TarotError("无法安全锁定会话。")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def load_state(path):
    try:
        if path.is_symlink() or not path.is_file():
            raise TarotError("找不到有效的会话文件。")
        with path.open(encoding="utf-8") as stream:
            state = json.load(stream)
    except (json.JSONDecodeError, UnicodeError):
        raise TarotError("会话文件无法解析；未改动牌序。") from None
    validate(state)
    return state


def serialize(state):
    return (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def create_state(path, state):
    # A hard link publishes a completely written file and refuses any existing target.
    fd, temp_name = tempfile.mkstemp(prefix=".tarot-new-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(serialize(state))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp_name, str(path))
        except FileExistsError:
            raise TarotError("会话已存在；请继续原会话或选择新的文件名，不能覆盖洗牌。") from None
    finally:
        os.unlink(temp_name)


def save_state(path, state):
    fd, temp_name = tempfile.mkstemp(prefix=".tarot-save-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(serialize(state))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, str(path))
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def new_session(args):
    positions = positions_for(args.spread, args.choices)
    random = secrets.SystemRandom()
    cards = [{"card_id": card_id,
              "orientation": "upright" if args.upright_only or random.getrandbits(1) == 0 else "reversed"}
             for card_id in CATALOG]
    random.shuffle(cards)
    state = {
        "version": VERSION, "session_id": str(uuid.uuid4()), "deck": DECK,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "awaiting_draw", "total_cards": 78, "spread": args.spread,
        "choices": args.choices, "orientation_mode": "upright-only" if args.upright_only else "mixed",
        "positions": positions, "cards": cards, "nonce": secrets.token_hex(32), "drawn": [],
        "base_positions_count": len(positions), "clarifier_round": 0, "clarifier_rounds": [],
    }
    state["commitment"] = digest(state)
    validate(state)
    create_state(args.session, state)
    return public_status(state)


def draw_cards(args, state):
    numbers = args.numbers
    if len(numbers) != len(set(numbers)):
        raise TarotError("一次抽牌不能包含重复编号；本次未抽出任何牌。")
    if any(number < 1 or number > 78 for number in numbers):
        raise TarotError("牌号必须在 1..78 之间；本次未抽出任何牌。")
    drawn_numbers = {draw["number"] for draw in state["drawn"]}
    if drawn_numbers.intersection(numbers):
        raise TarotError("包含已经抽过的牌号；本次未抽出任何牌。")
    if state["status"] == "complete":
        raise TarotError("当前牌阵已抽齐；如需补牌，请先开启补充澄清（clarify）。")
    if len(numbers) > len(state["positions"]) - len(state["drawn"]):
        raise TarotError("抽牌数量超过当前牌阵所需；本次未抽出任何牌。")
    for number in numbers:
        state["drawn"].append({"number": number, "position_index": len(state["drawn"]) + 1})
    if len(state["drawn"]) == len(state["positions"]):
        state["status"] = "complete"
    validate(state)
    save_state(args.session, state)
    return public_status(state)


def clarify(args, state):
    if state["status"] != "complete":
        raise TarotError("请先抽齐当前牌阵，再开启下一轮补充澄清。")
    count = args.count
    if type(count) is not int or count < 1:
        raise TarotError("补充澄清至少需要一张牌；未改动会话。")
    available = 78 - len(state["drawn"])
    if count > available:
        raise TarotError(f"补牌数量超过剩余的 {available} 张牌；未改动会话。")
    metadata = clarifier_metadata(state)
    round_number = metadata["clarifier_round"] + 1
    rounds = list(metadata["clarifier_rounds"])
    rounds.append({"round": round_number, "start_position_index": len(state["positions"]) + 1, "count": count})
    state.update({"base_positions_count": metadata["base_positions_count"],
                  "clarifier_round": round_number, "clarifier_rounds": rounds})
    state["positions"].extend(clarifier_positions(round_number, count))
    state["status"] = "awaiting_draw"
    validate(state)
    save_state(args.session, state)
    return public_status(state)


def reveal(state):
    if state["status"] != "complete":
        raise TarotError("牌阵尚未抽齐，不能公开剩余牌序。")
    return {**public_status(state), "nonce": state["nonce"],
            "full_deck": [public_card(card, number) for number, card in enumerate(state["cards"], 1)],
            "commitment_payload": commitment_payload(state),
            "commitment_payload_canonical": canonical(commitment_payload(state)),
            "commitment_algorithm": "SHA-256 / UTF-8 / JSON sort_keys=True, ensure_ascii=False, separators=(',', ':')"}


def main():
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    for command in ("new", "status", "draw", "clarify", "reveal"):
        sub = commands.add_parser(command)
        sub.add_argument("--session", required=True, type=session_path)
        if command == "new":
            sub.add_argument("--spread", choices=("general", "choice"), default="general")
            sub.add_argument("--choices", type=int)
            sub.add_argument("--upright-only", action="store_true")
        elif command == "draw":
            sub.add_argument("--numbers", type=int, nargs="+", required=True)
        elif command == "clarify":
            sub.add_argument("--count", type=int, default=1)
    try:
        args = parser.parse_args()
        with locked(args.session, create=args.command == "new"):
            if args.command == "new":
                result = new_session(args)
            else:
                state = load_state(args.session)
                result = (draw_cards(args, state) if args.command == "draw" else
                          clarify(args, state) if args.command == "clarify" else
                          reveal(state) if args.command == "reveal" else public_status(state))
        result["session_filename"] = args.session.name
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except TarotError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except OSError:
        print(json.dumps({"error": "无法安全读写会话文件；未输出隐藏牌序。"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
