import random
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
import socketio

BASE_DIR = Path(__file__).resolve().parent

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
app = FastAPI()

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

PALETTE = ["#8da2ff", "#ffffab", "#7ad58c", "#ff979b", "#c792ea", "#ffcb6b"]
rooms = {}

def calculate_points(multiplier_idx: int, click_count: int) -> int:
    base = [100, 200, 300, 400][multiplier_idx]
    return base * ((click_count % 5) + 1)

def get_serializable_state(room: dict) -> dict:
    return {
        "multiplier_idx": room["multiplier_idx"],
        "question_point": room["question_point"],
        "buzzer_active": room["buzzer_active"],
        "current_buzzer": room["current_buzzer"],
        "disqualified": list(room["disqualified"]),
        "players": [
            {"sid": s, "name": d["name"], "score": d["score"], "color": d["color"]}
            for s, d in room["players"].items()
        ]
    }

@app.get("/")
async def get_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@sio.event
async def create_room(sid):
    code = str(random.randint(1000, 9999))
    while code in rooms:
        code = str(random.randint(1000, 9999))
    rooms[code] = {
        "host_sid": sid,
        "multiplier_idx": 0,
        "click_count": 0,
        "question_point": 100,
        "buzzer_active": False,
        "current_buzzer": None,
        "disqualified": set(),
        "players": {}
    }
    await sio.save_session(sid, {"room": code, "role": "host"})
    await sio.enter_room(sid, code)
    await sio.emit("room_created", {"code": code, "state": get_serializable_state(rooms[code])}, to=sid)

@sio.event
async def join_room(sid, data):
    code = data.get("room", "").strip()
    name = data.get("name", "").strip() or f"Player {random.randint(1, 99)}"
    
    if code not in rooms:
        await sio.emit("join_error", {"msg": "Room not found"}, to=sid)
        return

    room = rooms[code]
    color = PALETTE[len(room["players"]) % len(PALETTE)]
    room["players"][sid] = {"name": name, "score": 0, "color": color}

    await sio.save_session(sid, {"room": code, "role": "player", "name": name})
    await sio.enter_room(sid, code)

    await sio.emit("joined_success", {
        "room": code,
        "name": name,
        "color": color,
        "buzzer_active": room["buzzer_active"],
        "buzzer_locked": room["current_buzzer"] is not None or sid in room["disqualified"]
    }, to=sid)

    await sync_room(code)

@sio.event
async def buzz(sid):
    session = await sio.get_session(sid)
    code = session.get("room")
    if not code or code not in rooms:
        return

    room = rooms[code]
    if not room["buzzer_active"] or room["current_buzzer"] is not None:
        return
    if sid in room["disqualified"]:
        return

    room["current_buzzer"] = sid
    buzzed_player = room["players"][sid]["name"]
    await sio.emit("player_buzzed", {"sid": sid, "name": buzzed_player}, room=code)
    await sync_room(code)

@sio.event
async def next_question(sid):
    room = await get_host_room(sid)
    if not room: return
    room["click_count"] += 1
    room["question_point"] = calculate_points(room["multiplier_idx"], room["click_count"])
    reset_question_state(room)
    await sync_room(get_room_code(sid))

@sio.event
async def new_topic(sid):
    room = await get_host_room(sid)
    if not room: return
    room["click_count"] = 0
    room["question_point"] = calculate_points(room["multiplier_idx"], 0)
    reset_question_state(room)
    await sync_room(get_room_code(sid))

@sio.event
async def set_multiplier(sid, data):
    room = await get_host_room(sid)
    if not room: return
    idx = data.get("index", 0)
    room["multiplier_idx"] = idx
    room["click_count"] = 0
    room["question_point"] = calculate_points(idx, 0)
    reset_question_state(room)
    await sync_room(get_room_code(sid))

@sio.event
async def answer_verdict(sid, data):
    room = await get_host_room(sid)
    if not room or not room["current_buzzer"]: return
    target_sid = room["current_buzzer"]
    correct = data.get("correct", False)
    code = get_room_code(sid)

    if correct:
        room["players"][target_sid]["score"] += room["question_point"]
        room["click_count"] += 1
        room["question_point"] = calculate_points(room["multiplier_idx"], room["click_count"])
        reset_question_state(room)
    else:
        room["players"][target_sid]["score"] -= room["question_point"]
        room["disqualified"].add(target_sid)
        room["current_buzzer"] = None
        room["buzzer_active"] = True

    await sync_room(code)

@sio.event
async def reset_game(sid):
    room = await get_host_room(sid)
    if not room: return
    room["multiplier_idx"] = 0
    room["click_count"] = 0
    room["question_point"] = 100
    for p in room["players"].values():
        p["score"] = 0
    reset_question_state(room)
    await sync_room(get_room_code(sid))

@sio.event
async def disconnect(sid):
    session = await sio.get_session(sid)
    if not session: return
    code = session.get("room")
    if code in rooms:
        if rooms[code]["host_sid"] == sid:
            await sio.emit("room_closed", room=code)
            del rooms[code]
        elif sid in rooms[code]["players"]:
            del rooms[code]["players"][sid]
            if rooms[code]["current_buzzer"] == sid:
                rooms[code]["current_buzzer"] = None
                rooms[code]["buzzer_active"] = True
            await sync_room(code)

def reset_question_state(room):
    room["buzzer_active"] = True
    room["current_buzzer"] = None
    room["disqualified"].clear()

def get_room_code(sid):
    for code, r in rooms.items():
        if r["host_sid"] == sid: return code
    return None

async def get_host_room(sid):
    code = get_room_code(sid)
    return rooms.get(code) if code else None

async def sync_room(code):
    if code not in rooms: return
    await sio.emit("room_state", get_serializable_state(rooms[code]), room=code)
