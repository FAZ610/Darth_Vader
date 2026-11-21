#!/usr/bin/env python3
"""Local mechfight arena: run your bots against each other on your own machine.

    python local_arena.py --bot t200.py:8 --bot baseline_bot.py:8 --matches 20

Each --bot is `path[:count]` (a Python bot script, run with this interpreter) or
`name=command...[:count]` is not supported; use scripts. Slots are shuffled every match.

This is an APPROXIMATION of the real server, written from protocol.md and the real
config (taken from the kit's recorded hello). It implements: movement with walls, roofs,
step-up, jumping and jets; energy; the gun, mortar (splash, concussion), laser (charge,
cook-off) and lightning (chain, short); rear armor; cubes and size; upgrades and offers;
crates, floor loot, weapon pickups/swaps; NPC drones; the shrinking zone; supply drops;
vision (range, FOV wedge, near sensors, buildings, 5 s memory); sound with bearing noise;
lockstep timing with the 50 ms budget, coasting and idling.

Known simplifications: no tree/canopy vision blocking, buildings as one solid interval per
1 m cell (plus a bridge layer), no roof-edge/eave special cases, no terrain max-slope rule
beyond step-up. Use it to rank your bots against each other, and trust real submissions
for absolute scores.
"""
import argparse
import gzip
import json
import math
import os
import queue
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(ROOT, "mechfight-kit")
ARENA = os.path.join(KIT, "arena")
TAU = 2 * math.pi
DT = 0.05


def wrap(a):
    return (a + math.pi) % TAU - math.pi


def load_config():
    with gzip.open(os.path.join(KIT, "check", "stream.jsonl.gz"), "rt", encoding="utf-8") as fh:
        hello = json.loads(fh.readline())
    return hello["config"]


def r2(v):
    return round(v, 2)


# ============================================================================ map


class Map:
    def __init__(self, arena_dir=ARENA):
        with open(os.path.join(arena_dir, "v2", "world.json"), "r", encoding="utf-8") as fh:
            world = json.load(fh)
        ter = world["terrain"]
        self.nx, self.ny = int(ter["nx"]), int(ter["ny"])
        self.x0, self.y0 = float(ter["minX"]), float(ter["minY"])
        assert float(ter["step"]) == 1.0
        raw = np.fromfile(os.path.join(arena_dir, "v2", "terrain.i16"), dtype="<i2")
        self.GR = (raw.reshape(self.ny, self.nx).astype(np.float32) * float(ter.get("scale", 0.01)))
        b = world["bounds"]
        self.bx0, self.bx1, self.by0, self.by1 = b["minX"], b["maxX"], b["minY"], b["maxY"]
        shape = (self.ny, self.nx)
        self.BB = np.full(shape, 1e9, np.float32)
        self.BT = np.full(shape, -1e9, np.float32)
        self.DB = np.full(shape, 1e9, np.float32)
        self.DT = np.full(shape, -1e9, np.float32)
        for p in world["prisms"]:
            deck = p.get("kind") == "bridge"
            self._fill([p["ring"]] + list(p.get("holes") or []), p["base"], p["top"],
                       self.DB if deck else self.BB, self.DT if deck else self.BT)
        # flat python lists for fast scalar access
        self.gr = self.GR.ravel().tolist()
        self.bb = self.BB.ravel().tolist()
        self.bt = self.BT.ravel().tolist()
        self.db = self.DB.ravel().tolist()
        self.dt = self.DT.ravel().tolist()
        # open-ground cells (no building/deck above ground) for spawning
        no_deck = (self.DT < self.GR - 9.5) | (self.DB > self.GR + 9.5)
        self.free = (self.BT < self.GR + 0.3) & no_deck
        roof = (self.BT > self.GR + 3) & (self.BT < self.GR + 55)
        self.roof_cells = np.argwhere(roof)

    def _fill(self, rings, base, top, A_base, A_top):
        edges = []
        for r in rings:
            pts = np.asarray(r, dtype=np.float64).reshape(-1, 2)
            edges.append(np.concatenate([pts, np.roll(pts, -1, axis=0)], axis=1))
        E = np.concatenate(edges)
        xa, ya, xb, yb = E[:, 0], E[:, 1], E[:, 2], E[:, 3]
        j0 = max(0, int(math.ceil(min(ya.min(), yb.min()) - self.y0)))
        j1 = min(self.ny - 1, int(math.floor(max(ya.max(), yb.max()) - self.y0)))
        if j1 < j0:
            return
        ys = self.y0 + np.arange(j0, j1 + 1, dtype=np.float64)
        Y = ys[:, None]
        cross = (ya[None, :] <= Y) != (yb[None, :] <= Y)
        with np.errstate(divide="ignore", invalid="ignore"):
            X = xa[None, :] + (Y - ya[None, :]) * (xb - xa)[None, :] / (yb - ya)[None, :]
        for r in range(cross.shape[0]):
            xs = np.sort(X[r][cross[r]])
            j = j0 + r
            for k in range(0, len(xs) - 1, 2):
                i0 = max(0, int(math.ceil(xs[k] - self.x0)))
                i1 = min(self.nx - 1, int(math.floor(xs[k + 1] - self.x0)))
                if i1 >= i0:
                    np.minimum(A_base[j, i0:i1 + 1], base, out=A_base[j, i0:i1 + 1])
                    np.maximum(A_top[j, i0:i1 + 1], top, out=A_top[j, i0:i1 + 1])

    # ---- scalar queries
    def idx(self, x, y):
        i = int(x - self.x0 + 0.5)
        j = int(y - self.y0 + 0.5)
        if i < 0:
            i = 0
        elif i >= self.nx:
            i = self.nx - 1
        if j < 0:
            j = 0
        elif j >= self.ny:
            j = self.ny - 1
        return j * self.nx + i

    def ground(self, x, y):
        fx, fy = x - self.x0, y - self.y0
        i = min(max(int(fx), 0), self.nx - 2)
        j = min(max(int(fy), 0), self.ny - 2)
        ax, ay = min(max(fx - i, 0.0), 1.0), min(max(fy - j, 0.0), 1.0)
        k = j * self.nx + i
        g = self.gr
        return (g[k] * (1 - ax) + g[k + 1] * ax) * (1 - ay) + (g[k + self.nx] * (1 - ax) + g[k + self.nx + 1] * ax) * ay

    def floor_at(self, k, zref):
        """Highest walkable surface at cell k that is at or below zref."""
        s = self.gr[k]
        t = self.bt[k]
        if s < t <= zref:
            s = t
        t = self.dt[k]
        if s < t <= zref:
            s = t
        return s

    def surface(self, x, y, zref):
        k = self.idx(x, y)
        s = self.gr[k]
        t = self.bt[k]
        if s < t <= zref:
            s = t
        t = self.dt[k]
        if s < t <= zref:
            s = t
        return s

    def wall(self, k, lo, hi):
        """Any solid in cell k overlapping the height band (lo, hi)?"""
        if self.bt[k] > lo and self.bb[k] < hi:
            return True
        if self.dt[k] > lo and self.db[k] < hi:
            return True
        return self.gr[k] > lo

    def solid(self, x, y, z):
        k = self.idx(x, y)
        if self.bb[k] < z < self.bt[k] or self.db[k] < z < self.dt[k]:
            return True
        return z < self.gr[k] - 0.05

    def out_of_bounds(self, x, y):
        return x < self.bx0 or x > self.bx1 or y < self.by0 or y > self.by1

    def los1(self, a, b, step=1.0):
        dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        n = int(math.hypot(dx, dy) / step) + 1
        for s in range(1, n):
            f = s / n
            if self.solid(a[0] + dx * f, a[1] + dy * f, a[2] + dz * f):
                return False
        return True

    def ray_wall(self, a, d, length, step=0.75):
        """Distance along unit 3D direction d from a to the first solid (or length)."""
        n = int(length / step)
        for s in range(1, n + 1):
            t = s * step
            if self.solid(a[0] + d[0] * t, a[1] + d[1] * t, a[2] + d[2] * t):
                return t - step * 0.5
        return length

    # ---- batch line of sight (numpy)
    def los_batch(self, A, B, step=1.25):
        A = np.asarray(A, dtype=np.float32).reshape(-1, 3)
        B = np.asarray(B, dtype=np.float32).reshape(-1, 3)
        n = len(A)
        if n == 0:
            return np.zeros(0, bool)
        D = B - A
        L = np.hypot(D[:, 0], D[:, 1])
        out = np.ones(n, bool)
        # bucket by length so short rays are not oversampled
        order = np.argsort(L)
        start = 0
        while start < n:
            end = min(n, start + 256)
            sel = order[start:end]
            K = max(2, int(math.ceil(float(L[sel].max()) / step)))
            ts = (np.arange(1, K, dtype=np.float32) / K)[None, :, None]
            P = A[sel, None, :] + D[sel, None, :] * ts
            i = np.clip(np.rint(P[..., 0] - self.x0).astype(np.int32), 0, self.nx - 1)
            j = np.clip(np.rint(P[..., 1] - self.y0).astype(np.int32), 0, self.ny - 1)
            z = P[..., 2]
            blk = (self.BB[j, i] < z) & (z < self.BT[j, i])
            blk |= (self.DB[j, i] < z) & (z < self.DT[j, i])
            blk |= z < self.GR[j, i] - 0.1
            out[sel] = ~blk.any(axis=1)
            start = end
        return out

    # ---- spawning helpers
    def random_open(self, rng, cx, cy, radius, tries=400):
        for _ in range(tries):
            a = rng.uniform(0, TAU)
            d = radius * math.sqrt(rng.random())
            x, y = cx + math.cos(a) * d, cy + math.sin(a) * d
            if x < self.bx0 + 30 or x > self.bx1 - 30 or y < self.by0 + 30 or y > self.by1 - 30:
                continue
            ok = True
            g0 = self.gr[self.idx(x, y)]
            for ox, oy in ((0, 0), (3, 0), (-3, 0), (0, 3), (0, -3), (6, 0), (-6, 0), (0, 6), (0, -6)):
                i = int(x + ox - self.x0 + 0.5)
                j = int(y + oy - self.y0 + 0.5)
                if not (0 <= i < self.nx and 0 <= j < self.ny) or not self.free[j, i]:
                    ok = False
                    break
                if abs(self.gr[j * self.nx + i] - g0) > 1.0:  # no cliffs / pits
                    ok = False
                    break
            if ok:
                return [x, y, g0]
        return None

    def random_roof(self, rng, cx, cy, radius):
        for _ in range(200):
            j, i = self.roof_cells[rng.randrange(len(self.roof_cells))]
            x, y = self.x0 + i, self.y0 + j
            if math.hypot(x - cx, y - cy) > radius:
                continue
            k = j * self.nx + i
            # require a little flat roof around
            if all(abs(self.bt[self.idx(x + ox, y + oy)] - self.bt[k]) < 0.3 for ox, oy in ((2, 0), (-2, 0), (0, 2), (0, -2))):
                return [x, y, float(self.bt[k])]
        return None


# ============================================================================ bot processes


class BotProc:
    """One bot process. Its stdout lines go to a queue shared by the whole match as (slot, line)."""

    def __init__(self, path, slot, shared_q, log_path=None):
        self.path = path
        self.slot = slot
        self.q = shared_q
        self.dead = False
        self.log = open(log_path, "w", encoding="utf-8") if log_path else subprocess.DEVNULL
        self.p = subprocess.Popen(
            [sys.executable, "-u", os.path.abspath(path)],
            cwd=os.path.dirname(os.path.abspath(path)),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
            text=True, encoding="utf-8", bufsize=1,
        )
        self.out = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._write, daemon=True).start()

    def _write(self):
        # Windows pipes have tiny buffers: writing from the main thread would block on each bot.
        while True:
            line = self.out.get()
            if line is None:
                break
            try:
                self.p.stdin.write(line)
                self.p.stdin.flush()
            except (OSError, ValueError):
                self.dead = True
                break
        try:
            self.p.stdin.close()
        except Exception:
            pass

    def _read(self):
        try:
            for line in self.p.stdout:
                self.q.put((self.slot, line))
        except Exception:
            pass
        self.q.put((self.slot, None))

    def send(self, msg):
        if self.dead:
            return
        self.out.put(json.dumps(msg, separators=(",", ":")) + "\n")

    def close(self):
        self.out.put(None)
        try:
            self.p.wait(timeout=3)
        except Exception:
            self.p.kill()
        if self.log is not subprocess.DEVNULL:
            self.log.close()


# ============================================================================ entities


class Weapon:
    __slots__ = ("kind", "cooldown", "ammo", "reload", "charge", "full_t", "equip")

    def __init__(self, kind, mag=0):
        self.kind = kind
        self.cooldown = 0.0
        self.ammo = mag
        self.reload = 0.0
        self.charge = 0.0
        self.full_t = 0.0
        self.equip = 0.0


class Mech:
    def __init__(self, mid, label, pos, cfg):
        self.id = mid
        self.label = label
        self.pos = list(pos)
        self.vel = [0.0, 0.0, 0.0]
        self.aim = [0.0, 0.0]
        self.cmd = {"move": [0.0, 0.0], "boost": False, "aim": [0.0, 0.0], "fire": [False, False]}
        self.jump = False
        self.alive = True
        self.cubes = 0
        self.upg = {}
        self.cfg = cfg
        self.recompute()
        self.max_hp = self.stats["hp"]
        self.hp = self.max_hp
        self.energy = self.stats["energy"]
        self.grounded = True
        self.weapons = [Weapon("gun", self.wstats["gun"]["mag"]), None]
        self.last_combat = -99.0
        self.last_spend = -99.0
        self.short_until = -1.0
        self.offer = None
        self.offer_queue = 0
        self.offer_seq = 0
        self.thresholds_hit = 0
        self.events = []
        self.zone_dmg = 0.0
        self.seen = {}
        self.kills = 0
        self.place = None
        self.death_t = None
        self.death_cause = None
        self.step_timer = 0.0
        self.jet_timer = 0.0
        self.last_answer_t = 0.0
        self.missed = 0
        self.late = 0
        self.dmg_dealt = 0.0
        self.last_hit_by = None
        self.last_obs_t = 0.0
        self.mortar_hits = 0

    def recompute(self):
        cfg = self.cfg
        st = dict(cfg["mech"])
        ws = {k: dict(v) for k, v in cfg["weapons"].items()}
        defs = {u["id"]: u for u in cfg["upgrades"]}
        for uid, n in self.upg.items():
            for _ in range(n):
                for eff in defs[uid]["effects"]:
                    parts = eff["path"].split(".")
                    tgt = st if parts[0] == "mech" else ws[parts[1]]
                    key = parts[-1]
                    if "mul" in eff:
                        tgt[key] = tgt[key] * eff["mul"]
                    if "add" in eff:
                        tgt[key] = tgt[key] + eff["add"]
        scale = 1 + cfg["cubes"]["size_per_cube"] * self.cubes
        for k in ("radius", "height", "eye_height", "muzzle_height"):
            st[k] = st[k] * scale
        self.stats = st
        self.wstats = ws
        cap = cfg["cubes"]["stat_cap"]
        self.dmg_mult = (1 + cfg["cubes"]["damage_per_cube"] * min(self.cubes, cap)) * getattr(self, "perk_dmg", 1.0)
        new_max = st["hp"] * (1 + cfg["cubes"]["hp_per_cube"] * min(self.cubes, cap)) * getattr(self, "perk_hp", 1.0)
        if hasattr(self, "max_hp"):
            if new_max > self.max_hp:
                self.hp += new_max - self.max_hp
            self.max_hp = new_max
            self.hp = min(self.hp, self.max_hp)

    def holds(self, kind):
        return any(w is not None and w.kind == kind for w in self.weapons)

    def charging(self):
        return any(w is not None and w.kind == "laser" and w.charge > 0 for w in self.weapons)


class NPC:
    def __init__(self, nid, pos):
        self.id = nid
        self.home = list(pos)
        self.pos = list(pos)
        self.vel = [0.0, 0.0, 0.0]
        self.aim = [0.0, 0.0]
        self.hp = 0
        self.max_hp = 0
        self.target = None
        self.cooldown = 0.0
        self.wander = None
        self.alive = True


# ============================================================================ match


class Match:
    def __init__(self, cfg, mp, lineup, seed, budget_ms, log_dir=None, replay=None, verbose=False):
        self.cfg = cfg
        self.map = mp
        self.rng = random.Random(seed)
        self.seed = seed
        self.budget = budget_ms / 1000.0
        self.verbose = verbose
        self.t = 0.0
        self.tick_n = 0
        self.next_id = {"crate": 1000, "cube": 5000, "pick": 8000, "proj": 100000, "drop": 20000}
        self.sounds = []
        self.beams = []
        self.projectiles = []
        self.crates = {}
        self.cubes = {}
        self.pickups = {}
        self.drops = []
        self.dropped_called = 0
        self.replay = replay
        self.los_cache = {}
        self._setup_zone()

        rng = self.rng
        zc, zr = cfg["zone"]["start_center"], cfg["zone"]["start_radius"]
        frac = cfg["match"]["spawn_zone_fraction"]
        sep = cfg["match"]["spawn_min_separation"]
        slots = list(range(len(lineup)))
        rng.shuffle(slots)
        self.mechs = []
        spawns = []
        for sl in range(len(lineup)):
            p = None
            for attempt in range(300):
                q = mp.random_open(rng, zc[0], zc[1], zr * frac)
                if q is None:
                    continue
                need = sep if attempt < 200 else sep * 0.5
                if all(math.hypot(q[0] - s[0], q[1] - s[1]) >= need for s in spawns):
                    p = q
                    break
            if p is None:
                p = mp.random_open(rng, zc[0], zc[1], zr * frac)
            spawns.append(p)
        self.procs = []
        self.inbox = queue.Queue()
        for sl in range(len(lineup)):
            entry = lineup[slots[sl]]
            label, path = entry[0], entry[1]
            perks = entry[2] if len(entry) > 2 else {}
            m = Mech(sl, label, spawns[sl], cfg)
            # Perks make pool opponents stronger than the rules alone allow (to stand in for
            # built-in bots that beat ours): hp / dmg multipliers, gun spread multiplier, start cubes.
            m.perk_hp = float(perks.get("hp", 1.0))
            m.perk_dmg = float(perks.get("dmg", 1.0))
            m.perk_spread = float(perks.get("spread", 1.0))
            # hunt: this opponent cannot see other hunters, so it only engages the bots under test
            m.perk_hunt = bool(perks.get("hunt", 0))
            m.recompute()
            m.hp = m.max_hp
            m.start_cubes = int(perks.get("cubes", 0))
            m.aim = [rng.uniform(-math.pi, math.pi), 0.0]
            m.cmd["aim"] = list(m.aim)
            self.mechs.append(m)
            log_path = os.path.join(log_dir, "m%d_slot%02d_%s.log" % (seed, sl, label)) if log_dir else None
            self.procs.append(BotProc(path, sl, self.inbox, log_path))

        ncfg = cfg["npc"]
        self.npcs = []
        for k in range(ncfg["count"]):
            p = mp.random_open(rng, zc[0], zc[1], zr * 0.9)
            if p:
                n = NPC(100 + k, p)
                n.hp = n.max_hp = ncfg["hp"]
                self.npcs.append(n)
        for _ in range(cfg["crates"]["count"]):
            p = self._loot_spot(cfg["crates"]["roof_fraction"])
            if p:
                cid = self._nid("crate")
                self.crates[cid] = {"id": cid, "pos": p, "hp": cfg["crates"]["hp"]}
        for _ in range(cfg["loot"]["floor_count"]):
            p = self._loot_spot(cfg["loot"]["floor_roof_fraction"])
            if p:
                self._spawn_pickup(self._random_weapon(), p)

    # ---------------------------------------------------------------- setup helpers
    def _nid(self, kind):
        self.next_id[kind] += 1
        return self.next_id[kind] - 1

    def _loot_spot(self, roof_frac):
        zc, zr = self.cfg["zone"]["start_center"], self.cfg["zone"]["start_radius"]
        if self.rng.random() < roof_frac:
            p = self.map.random_roof(self.rng, zc[0], zc[1], zr)
            if p:
                return p
        return self.map.random_open(self.rng, zc[0], zc[1], zr)

    def _random_weapon(self):
        w = self.cfg["loot"]["weights"]
        kinds = [k for k in w if w[k] > 0]
        return self.rng.choices(kinds, weights=[w[k] for k in kinds])[0]

    def _spawn_pickup(self, kind, pos, state=None):
        pid = self._nid("pick")
        self.pickups[pid] = {"id": pid, "kind": kind, "pos": list(pos), "state": state}
        return pid

    def _spawn_cube(self, pos, scatter=0.0):
        cid = self._nid("cube")
        x, y = pos[0], pos[1]
        if scatter:
            a = self.rng.uniform(0, TAU)
            d = self.rng.uniform(0, scatter)
            x2, y2 = x + math.cos(a) * d, y + math.sin(a) * d
            if not self.map.wall(self.map.idx(x2, y2), pos[2] + 1.2, pos[2] + 3):
                x, y = x2, y2
        z = self.map.surface(x, y, pos[2] + 1.0)
        self.cubes[cid] = {"id": cid, "pos": [x, y, z]}

    def _setup_zone(self):
        zc = self.cfg["zone"]
        cx, cy = zc["start_center"]
        r = zc["start_radius"]
        t = 0.0
        self.phases = []
        for ph in zc["phases"]:
            nr = ph["radius"]
            slack = max(0.0, r - nr)
            a = self.rng.uniform(0, TAU)
            d = slack * math.sqrt(self.rng.random()) * 0.9
            nx, ny = cx + math.cos(a) * d, cy + math.sin(a) * d
            s0 = t + ph["hold_s"]
            s1 = s0 + ph["shrink_s"]
            self.phases.append({"start": t, "s0": s0, "s1": s1, "c": (cx, cy), "r": r,
                                "nc": (nx, ny), "nr": nr, "dps": ph["dps"]})
            cx, cy, r, t = nx, ny, nr, s1

    def zone_phase(self, t):
        for ph in self.phases:
            if t < ph["s1"]:
                return ph
        return self.phases[-1]

    def zone_circle(self, t):
        ph = self.zone_phase(t)
        if t <= ph["s0"]:
            f = 0.0
        else:
            f = min(1.0, (t - ph["s0"]) / (ph["s1"] - ph["s0"]))
        return (ph["c"][0] + (ph["nc"][0] - ph["c"][0]) * f,
                ph["c"][1] + (ph["nc"][1] - ph["c"][1]) * f,
                ph["r"] + (ph["nr"] - ph["r"]) * f, ph["dps"])

    # ---------------------------------------------------------------- sounds
    def emit(self, kind, pos, src=None):
        self.sounds.append((self.t, kind, pos[0], pos[1], src))

    # ---------------------------------------------------------------- run
    def run(self):
        cfg = self.cfg
        for m in self.mechs:
            if m.start_cubes:
                self.give_cube(m, m.start_cubes)
                m.hp = m.max_hp
        hello_budget = cfg["bot"]["hello_budget_ms"] / 1000.0
        for m, p in zip(self.mechs, self.procs):
            p.send({"type": "hello", "protocol": "mechfight/1", "slot": m.id,
                    "seed": self.rng.randrange(2 ** 32),
                    "map": {"dir": ARENA, "files": ["v2/world.json", "v2/terrain.i16"]},
                    "config": cfg})
        deadline = time.perf_counter() + hello_budget
        waiting = set(range(len(self.procs)))
        while waiting:
            got = self.next_msg(deadline)
            if got is None:
                break
            slot, msg = got
            if msg is None or msg.get("type") == "ready":
                waiting.discard(slot)
        duration = cfg["match"]["duration_s"]
        decide = cfg["match"]["decide_every"]
        wall0 = time.perf_counter()
        prof = {"obs": 0.0, "wait": 0.0, "sim": 0.0}
        while True:
            alive = [m for m in self.mechs if m.alive]
            if len(alive) <= 1 or self.t >= duration - 1e-9:
                break
            t0 = time.perf_counter()
            obs = self.build_obs(alive)
            t1 = time.perf_counter()
            for m in alive:
                self.procs[m.id].send(obs[m.id])
            actions = self.collect(alive)
            t2 = time.perf_counter()
            for m in alive:
                self.apply_action(m, actions.get(m.id))
            for _ in range(decide):
                self.step()
                if sum(1 for m in self.mechs if m.alive) <= 1:
                    break
            t3 = time.perf_counter()
            prof["obs"] += t1 - t0
            prof["wait"] += t2 - t1
            prof["sim"] += t3 - t2
            if self.replay is not None and self.tick_n % 10 == 0:
                self.record_frame()
        # final placements
        survivors = sorted([m for m in self.mechs if m.alive], key=lambda m: -m.hp)
        for k, m in enumerate(survivors):
            m.place = k + 1
            m.death_cause = "survived"
            self.procs[m.id].send({"type": "end", "place": m.place, "kills": m.kills})
        for p in self.procs:
            p.close()
        wall = time.perf_counter() - wall0
        if self.verbose:
            print("match %d: %.1fs sim-time in %.1fs wall  obs %.1fs wait %.1fs sim %.1fs" % (
                self.seed, self.t, wall, prof["obs"], prof["wait"], prof["sim"]), file=sys.stderr)
        return {
            "seed": self.seed, "duration": self.t, "wall": wall,
            "mechs": [{
                "slot": m.id, "label": m.label, "place": m.place, "points": 16 - m.place,
                "kills": m.kills, "cubes": m.cubes, "death_t": m.death_t, "cause": m.death_cause,
                "damage": round(m.dmg_dealt), "missed": m.missed,
                "weapons": [w.kind for w in m.weapons if w],
            } for m in self.mechs],
        }

    def collect(self, alive):
        """Read one answer per alive bot for the current tick within the budget."""
        actions = {}
        tick = self.tick_n
        deadline = time.perf_counter() + self.budget
        pending = {m.id for m in alive if not self.procs[m.id].dead}
        while pending:
            got = self.next_msg(deadline)
            if got is None:
                break
            slot, msg = got
            if msg is None:
                pending.discard(slot)
                continue
            if slot in pending and isinstance(msg, dict) and msg.get("tick") == tick:
                actions[slot] = msg
                pending.discard(slot)
        return actions

    def next_msg(self, deadline):
        """(slot, parsed message | None at EOF) from any bot, or None when the deadline passes."""
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return None
            try:
                slot, line = self.inbox.get(timeout=remaining)
            except queue.Empty:
                return None
            if line is None:
                self.procs[slot].dead = True
                return slot, None
            try:
                return slot, json.loads(line)
            except ValueError:
                continue  # bad line: ignored, like the server

    # ---------------------------------------------------------------- actions
    def apply_action(self, m, a):
        coast = self.cfg["bot"]["coast_s"]
        if a is None:
            m.missed += 1
            if self.t - m.last_answer_t > coast:
                m.cmd["move"] = [0.0, 0.0]
                m.cmd["boost"] = False
            m.cmd["fire"] = [False, False]
            m.jump = False
            return
        m.last_answer_t = self.t
        mv = a.get("move", [0, 0])
        try:
            mx, my = float(mv[0]), float(mv[1])
            ln = math.hypot(mx, my)
            if ln > 1:
                mx, my = mx / ln, my / ln
        except Exception:
            mx = my = 0.0
        m.cmd["move"] = [mx, my]
        m.cmd["boost"] = bool(a.get("boost", False))
        if "aim" in a:
            try:
                m.cmd["aim"] = [float(a["aim"][0]), float(a["aim"][1])]
            except Exception:
                pass
        f = a.get("fire", [False, False])
        try:
            m.cmd["fire"] = [bool(f[0]), bool(f[1])]
        except Exception:
            m.cmd["fire"] = [False, False]
        m.jump = bool(a.get("jump", False))
        if a.get("reload"):
            for w in m.weapons:
                if w and w.kind == "gun" and w.reload <= 0 and w.ammo < m.wstats["gun"]["mag"]:
                    w.reload = m.wstats["gun"]["reload"]
                    self.emit("reload", m.pos, m.id)
        if "pick" in a and m.offer is not None:
            try:
                i = int(a["pick"])
                if 0 <= i < len(m.offer["choices"]):
                    self.resolve_offer(m, i)
            except Exception:
                pass
        if "take" in a and a["take"] is not None:
            self.do_take(m, a["take"], a.get("drop"))
        elif "drop" in a and a["drop"] in (0, 1):
            self.do_drop(m, a["drop"])

    def do_take(self, m, pid, drop):
        pk = self.pickups.get(pid)
        ev = {"type": "take_failed", "id": pid}
        if pk is None:
            ev["reason"] = "gone"
            m.events.append(ev)
            return
        if (math.hypot(pk["pos"][0] - m.pos[0], pk["pos"][1] - m.pos[1]) > self.cfg["loot"]["pickup_radius"]
                or abs(pk["pos"][2] - m.pos[2]) > 4):
            ev["reason"] = "range"
            m.events.append(ev)
            return
        if m.holds(pk["kind"]) and not (drop in (0, 1) and m.weapons[drop] and m.weapons[drop].kind == pk["kind"]):
            ev["reason"] = "have"
            m.events.append(ev)
            return
        slot = None
        if drop in (0, 1):
            slot = drop
        else:
            for s in (0, 1):
                if m.weapons[s] is None:
                    slot = s
                    break
        if slot is None:
            ev["reason"] = "full"
            m.events.append(ev)
            return
        old = m.weapons[slot]
        if old is not None and old.kind == "laser" and old.charge > 0:
            ev["reason"] = "busy"
            m.events.append(ev)
            return
        del self.pickups[pid]
        if old is not None:
            nid = self._spawn_pickup(old.kind, m.pos, state=old)
            m.events.append({"type": "dropped", "id": nid, "kind": old.kind, "slot": slot})
        w = pk["state"] if pk["state"] is not None else Weapon(pk["kind"], m.wstats["gun"]["mag"] if pk["kind"] == "gun" else 0)
        w.charge = 0.0
        w.full_t = 0.0
        w.equip = max(self.cfg["loot"]["equip_s"], m.wstats[w.kind]["cooldown"])
        m.weapons[slot] = w
        m.events.append({"type": "took", "id": pid, "kind": w.kind, "slot": slot})

    def do_drop(self, m, slot):
        w = m.weapons[slot]
        if w is None or (w.kind == "laser" and w.charge > 0):
            return
        m.weapons[slot] = None
        nid = self._spawn_pickup(w.kind, m.pos, state=w)
        m.events.append({"type": "dropped", "id": nid, "kind": w.kind, "slot": slot})

    # ---------------------------------------------------------------- upgrades / cubes
    def give_cube(self, m, n=1):
        m.cubes += n
        m.recompute()
        th = self.cfg["cubes"]["upgrade_thresholds"]
        while m.thresholds_hit < len(th) and m.cubes >= th[m.thresholds_hit]:
            m.thresholds_hit += 1
            m.offer_queue += 1
        self.next_offer(m)

    def next_offer(self, m):
        if m.offer is not None or m.offer_queue <= 0:
            return
        held = {w.kind for w in m.weapons if w}
        elig = []
        for u in self.cfg["upgrades"]:
            if m.upg.get(u["id"], 0) >= u["max"]:
                continue
            req = u.get("requires")
            if req and req not in held:
                continue
            elig.append(u)
        if not elig:
            m.offer_queue = 0
            return
        ch = self.rng.sample(elig, min(3, len(elig)))
        m.offer_seq += 1
        m.offer = {"id": m.offer_seq, "expires": r2(self.t + self.cfg["bot"]["offer_timeout_s"]),
                   "choices": [{"id": u["id"], "name": u["name"], "desc": u["desc"]} for u in ch]}
        m.offer_queue -= 1

    def resolve_offer(self, m, i):
        uid = m.offer["choices"][i]["id"]
        m.upg[uid] = m.upg.get(uid, 0) + 1
        old_max_e = m.stats["energy"]
        m.recompute()
        if m.stats["energy"] > old_max_e:
            m.energy += m.stats["energy"] - old_max_e
        m.events.append({"type": "upgrade", "id": uid})
        m.offer = None
        self.next_offer(m)

    # ---------------------------------------------------------------- damage
    def damage(self, target, amount, weapon, attacker, src, effect=None):
        """Apply weapon damage. target: Mech, NPC or crate dict. src: point it came from."""
        if amount <= 0:
            return
        if isinstance(target, Mech):
            if not target.alive:
                return
            rear = False
            if weapon != "zone":
                amount *= max(0.0, 1 - target.stats.get("armor", 0))
                bearing = math.atan2(src[1] - target.pos[1], src[0] - target.pos[0])
                if abs(wrap(bearing - target.aim[0])) > math.radians(target.stats["front_arc_deg"]) / 2:
                    amount *= target.stats["rear_mult"]
                    rear = True
            else:
                bearing = None
            target.hp -= amount
            target.last_combat = self.t
            ev = {"type": "damaged", "amount": r2(amount), "weapon": weapon,
                  "bearing": r2(bearing) if bearing is not None else None,
                  "by": attacker.id if attacker is not None else None}
            if rear:
                ev["rear"] = True
            target.events.append(ev)
            if attacker is not None:
                target.last_hit_by = (attacker, weapon)
            if isinstance(attacker, Mech):
                attacker.last_combat = self.t
                attacker.dmg_dealt += amount
                hev = {"type": "hit", "target": target.id, "amount": r2(amount), "weapon": weapon}
                if effect:
                    hev["effect"] = effect
                if rear:
                    hev["rear"] = True
                attacker.events.append(hev)
            if effect:
                target.events.append({"type": "effect", "effect": effect,
                                      "by": attacker.id if attacker is not None else None})
            if target.hp <= 0:
                target.hp = 0
                target._killer = (attacker, weapon)
        elif isinstance(target, NPC):
            if not target.alive:
                return
            target.hp -= amount
            if isinstance(attacker, Mech):
                target.target = attacker.id
                attacker.last_combat = self.t
                attacker.dmg_dealt += amount
                attacker.events.append({"type": "hit", "target": target.id, "amount": r2(amount), "weapon": weapon})
            if target.hp <= 0:
                target.alive = False
                for _ in range(self.cfg["npc"]["cubes"]):
                    self._spawn_cube(target.pos, 2.0)
                self.emit("death", target.pos)
        else:  # crate
            if target["id"] not in self.crates:
                return
            target["hp"] -= amount
            if isinstance(attacker, Mech):
                attacker.events.append({"type": "hit", "target": target["id"], "amount": r2(amount), "weapon": weapon})
            if target["hp"] <= 0:
                del self.crates[target["id"]]
                self.emit("crate", target["pos"])
                for _ in range(self.cfg["crates"]["cubes"]):
                    self._spawn_cube(target["pos"], 1.0)
                if self.rng.random() < self.cfg["loot"]["crate_weapon_chance"]:
                    self._spawn_pickup(self._random_weapon(), target["pos"])

    # ---------------------------------------------------------------- geometry helpers
    def bodies(self, exclude=None):
        """(entity, x, y, zbase, radius, height) for everything that can be hit."""
        out = []
        for m in self.mechs:
            if m.alive and m is not exclude:
                out.append((m, m.pos[0], m.pos[1], m.pos[2], m.stats["radius"], m.stats["height"]))
        nc = self.cfg["npc"]
        for n in self.npcs:
            if n.alive and n is not exclude:
                out.append((n, n.pos[0], n.pos[1], n.pos[2], nc["radius"], nc["height"]))
        cc = self.cfg["crates"]
        for c in self.crates.values():
            out.append((c, c["pos"][0], c["pos"][1], c["pos"][2], cc["radius"], cc["height"]))
        return out

    @staticmethod
    def seg_cyl(p0, p1, cx, cy, zb, r, h):
        """Parameter s in [0,1] where segment p0->p1 first touches the cylinder, or None."""
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        fx, fy = p0[0] - cx, p0[1] - cy
        a = dx * dx + dy * dy
        c = fx * fx + fy * fy - r * r
        if a < 1e-12:
            s_list = [0.0] if c <= 0 else []
        else:
            b = 2 * (fx * dx + fy * dy)
            disc = b * b - 4 * a * c
            if disc < 0:
                return None
            sq = math.sqrt(disc)
            s1 = (-b - sq) / (2 * a)
            s2 = (-b + sq) / (2 * a)
            if s2 < 0 or s1 > 1:
                return None
            s_list = [max(0.0, s1), min(1.0, s2)]
        dz = p1[2] - p0[2]
        for s in s_list + ([(s_list[0] + s_list[-1]) / 2] if s_list else []):
            z = p0[2] + dz * s
            if zb <= z <= zb + h:
                return s
        return None

    # ---------------------------------------------------------------- simulation step (1 tick)
    def step(self):
        cfg = self.cfg
        self.t = round(self.t + DT, 4)
        self.tick_n += 1
        t = self.t
        for m in self.mechs:
            if m.alive:
                self.move_mech(m)
        self.push_apart()
        for m in self.mechs:
            if m.alive:
                self.weapons_tick(m)
        self.npc_tick()
        self.projectiles_tick()
        # zone, regen, energy
        cx, cy, r, dps = self.zone_circle(t)
        for m in self.mechs:
            if not m.alive:
                continue
            inside = math.hypot(m.pos[0] - cx, m.pos[1] - cy) <= r
            m.in_zone = inside
            if not inside:
                m.hp -= dps * DT
                m.zone_dmg += dps * DT
                m.last_combat = t
                if m.hp <= 0:
                    m.hp = 0
                    m._killer = (None, "zone")
            elif t - m.last_combat >= m.stats["regen_delay"] and m.hp < m.max_hp:
                m.hp = min(m.max_hp, m.hp + m.stats["regen_per_s"] * DT)
            if t - m.last_spend >= m.stats["energy_regen_delay"]:
                m.energy = min(m.stats["energy"], m.energy + m.stats["energy_regen"] * DT)
            if m.offer is not None and t >= m.offer["expires"]:
                self.resolve_offer(m, 0)
        self.cube_pickups()
        self.drops_tick()
        self.deaths()

    def move_mech(self, m):
        st = m.stats
        mp = self.map
        t = self.t
        # aim slew
        ty, tp = m.cmd["aim"]
        tp = min(max(tp, st["min_pitch"]), st["max_pitch"])
        dyaw = wrap(ty - m.aim[0])
        lim = st["turn_rate"] * DT
        m.aim[0] = wrap(m.aim[0] + max(-lim, min(lim, dyaw)))
        dp = tp - m.aim[1]
        lim = st["pitch_rate"] * DT
        m.aim[1] += max(-lim, min(lim, dp))

        mvx, mvy = m.cmd["move"]
        moving = abs(mvx) + abs(mvy) > 1e-3
        boost = m.cmd["boost"] and m.energy > 0
        speed = st["walk_speed"]
        boosting_ground = False
        if boost and m.grounded and moving:
            speed = st["boost_speed"]
            m.energy = max(0.0, m.energy - st["boost_drain"] * DT)
            m.last_spend = t
            boosting_ground = True
        if m.charging():
            speed *= st["charge_move_mult"]
        dvx, dvy = mvx * speed - m.vel[0], mvy * speed - m.vel[1]
        acc = (st["ground_accel"] if m.grounded else st["air_accel"]) * DT
        dl = math.hypot(dvx, dvy)
        if dl > acc:
            dvx, dvy = dvx * acc / dl, dvy * acc / dl
        m.vel[0] += dvx
        m.vel[1] += dvy
        jetting = False
        if m.jump and m.grounded:
            m.vel[2] = st["jump_speed"]
            m.grounded = False
            self.emit("jet", m.pos, m.id)
        m.jump = False
        if not m.grounded:
            if boost:
                m.vel[2] = min(m.vel[2] + st["jet_accel"] * DT, st["max_rise_speed"])
                m.energy = max(0.0, m.energy - st["jet_drain"] * DT)
                m.last_spend = t
                jetting = True
            m.vel[2] -= st["gravity"] * DT

        # horizontal move with wall sliding
        x, y, z = m.pos
        nx_, ny_ = x + m.vel[0] * DT, y + m.vel[1] * DT
        ok, nz = self.can_stand(m, nx_, ny_, z)
        if not ok:
            ok1, nz1 = self.can_stand(m, nx_, y, z)
            ok2, nz2 = self.can_stand(m, x, ny_, z)
            if ok1 and abs(m.vel[0]) >= abs(m.vel[1]) * 0.2:
                ny_, nz = y, nz1
                m.vel[1] = 0.0
                ok = True
            elif ok2:
                nx_, nz = x, nz2
                m.vel[0] = 0.0
                ok = True
            elif ok1:
                ny_, nz = y, nz1
                m.vel[1] = 0.0
                ok = True
        if ok:
            x, y = nx_, ny_
            if m.grounded and nz > z:
                z = nz  # step up
        else:
            m.vel[0] = m.vel[1] = 0.0
        # vertical
        k = mp.idx(x, y)
        floor = mp.floor_at(k, z + (st["step_up"] if m.grounded else 0.05))
        if m.grounded:
            if z - floor <= 0.6:  # follow ground down slopes
                z = floor
                m.vel[2] = 0.0
            else:
                m.grounded = False
        if not m.grounded:
            nzv = z + m.vel[2] * DT
            if m.vel[2] > 0 and mp.wall(k, z + st["height"] - 0.01, nzv + st["height"]):
                m.vel[2] = 0.0  # ceiling
                nzv = z
            if nzv <= floor:
                nzv = floor
                m.vel[2] = 0.0
                m.grounded = True
            z = nzv
        x = min(max(x, mp.bx0 + st["radius"]), mp.bx1 - st["radius"])
        y = min(max(y, mp.by0 + st["radius"]), mp.by1 - st["radius"])
        m.pos = [x, y, z]
        # movement sounds
        hs = math.hypot(m.vel[0], m.vel[1])
        if m.grounded and hs > self.cfg["sound"]["step_speed"]:
            m.step_timer += DT
            if m.step_timer >= self.cfg["sound"]["step_every"]:
                m.step_timer = 0.0
                self.emit("boost" if boosting_ground else "step", m.pos, m.id)
        if jetting:
            m.jet_timer += DT
            if m.jet_timer >= 0.3:
                m.jet_timer = 0.0
                self.emit("jet", m.pos, m.id)

    def can_stand(self, m, x, y, z):
        """Can the mech's cylinder occupy (x, y) starting from feet height z? Returns (ok, new_z)."""
        mp = self.map
        st = m.stats
        if mp.out_of_bounds(x, y):
            return False, z
        k = mp.idx(x, y)
        step = st["step_up"] if m.grounded else 0.05
        if mp.gr[k] > z + step:
            return False, z  # terrain too steep / cliff
        nz = max(z, mp.floor_at(k, z + step)) if m.grounded else z
        lo = nz + step if m.grounded else nz + 0.05
        hi = nz + st["height"]
        r = st["radius"] * 0.85
        bb, bt, db, dt = mp.bb, mp.bt, mp.db, mp.dt
        for ox, oy in ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r), (0.7 * r, 0.7 * r), (-0.7 * r, 0.7 * r),
                       (0.7 * r, -0.7 * r), (-0.7 * r, -0.7 * r)):
            kk = mp.idx(x + ox, y + oy)
            if (bt[kk] > lo and bb[kk] < hi) or (dt[kk] > lo and db[kk] < hi):
                return False, z
        return True, nz

    def push_apart(self):
        ms = [m for m in self.mechs if m.alive]
        for i in range(len(ms)):
            a = ms[i]
            for j in range(i + 1, len(ms)):
                b = ms[j]
                dx, dy = b.pos[0] - a.pos[0], b.pos[1] - a.pos[1]
                rr = a.stats["radius"] + b.stats["radius"]
                if abs(dx) > rr or abs(dy) > rr:
                    continue
                d = math.hypot(dx, dy)
                if d >= rr or abs(a.pos[2] - b.pos[2]) > max(a.stats["height"], b.stats["height"]):
                    continue
                if d < 1e-6:
                    dx, dy, d = 1.0, 0.0, 1.0
                push = (rr - d) / 2
                ux, uy = dx / d, dy / d
                for mm, sgn in ((a, -1), (b, 1)):
                    nx_, ny_ = mm.pos[0] + ux * push * sgn, mm.pos[1] + uy * push * sgn
                    ok, _ = self.can_stand(mm, nx_, ny_, mm.pos[2])
                    if ok:
                        mm.pos[0], mm.pos[1] = nx_, ny_

    # ---------------------------------------------------------------- weapons
    def muzzle(self, m):
        return [m.pos[0], m.pos[1], m.pos[2] + m.stats["muzzle_height"]]

    @staticmethod
    def aim_dir(yaw, pitch):
        cp = math.cos(pitch)
        return (cp * math.cos(yaw), cp * math.sin(yaw), math.sin(pitch))

    def shot_origin(self, m, base, d):
        off = m.stats["radius"] + 0.5
        wall = self.map.ray_wall(base, d, off, step=0.5)
        off = min(off, wall)
        return [base[0] + d[0] * off, base[1] + d[1] * off, base[2] + d[2] * off]

    def weapons_tick(self, m):
        t = self.t
        for slot, w in enumerate(m.weapons):
            if w is None:
                continue
            ws = m.wstats[w.kind]
            held = m.cmd["fire"][slot]
            if w.equip > 0:
                w.equip = max(0.0, w.equip - DT)
            if w.cooldown > 0:
                w.cooldown -= DT
            if w.kind == "gun":
                if w.reload > 0:
                    w.reload -= DT
                    if w.reload <= 0:
                        w.reload = 0.0
                        w.ammo = int(ws["mag"])
                if held and w.equip <= 0 and w.reload <= 0 and w.ammo > 0 and w.cooldown <= 0:
                    w.cooldown += ws["cooldown"]
                    if w.cooldown < 0:
                        w.cooldown = ws["cooldown"]
                    w.ammo -= 1
                    sp = math.radians(ws["spread_deg"]) * m.perk_spread
                    yaw = m.aim[0] + self.rng.gauss(0, sp)
                    pit = m.aim[1] + self.rng.gauss(0, sp)
                    d = self.aim_dir(yaw, pit)
                    o = self.shot_origin(m, self.muzzle(m), d)
                    self.projectiles.append({
                        "id": self._nid("proj"), "kind": "gun", "owner": m, "pos": o,
                        "vel": [d[0] * ws["speed"], d[1] * ws["speed"], d[2] * ws["speed"]],
                        "left": ws["range"], "dmg": ws["damage"] * m.dmg_mult, "r": self.cfg["projectile"]["gun_radius"]})
                    self.emit("gun", m.pos, m.id)
                    if w.ammo <= 0:
                        w.reload = ws["reload"]
                        self.emit("reload", m.pos, m.id)
                if w.cooldown < 0 and not held:
                    w.cooldown = 0.0
            elif w.kind == "mortar":
                if held and w.equip <= 0 and w.cooldown <= 0:
                    w.cooldown = ws["cooldown"]
                    d = self.aim_dir(m.aim[0], m.aim[1])
                    base = [m.pos[0], m.pos[1], m.pos[2] + m.stats["height"] + 0.5]
                    o = self.shot_origin(m, base, d)
                    self.projectiles.append({
                        "id": self._nid("proj"), "kind": "mortar", "owner": m, "pos": o,
                        "vel": [d[0] * ws["speed"], d[1] * ws["speed"], d[2] * ws["speed"]],
                        "ttl": ws["ttl"], "dmg": ws["damage"] * m.dmg_mult, "r": 0.4})
                    self.emit("mortar", m.pos, m.id)
            elif w.kind == "laser":
                if t < m.short_until:
                    w.charge = 0.0
                    w.full_t = 0.0
                    continue
                fire_now = False
                if held and w.equip <= 0 and w.cooldown <= 0:
                    if w.charge == 0:
                        self.emit("laser_charge", m.pos, m.id)
                    w.charge = min(ws["charge"], w.charge + DT)
                    if w.charge >= ws["charge"] - 1e-9:
                        w.full_t += DT
                        if w.full_t >= ws["hold_s"]:
                            fire_now = True
                elif w.charge > 0:
                    if w.charge < ws["min_charge"]:
                        w.charge += DT
                        if w.charge >= ws["min_charge"]:
                            fire_now = True
                    else:
                        fire_now = True
                if fire_now:
                    self.fire_laser(m, w, ws)
            elif w.kind == "lightning":
                cost = ws["energy"]
                if held and w.equip <= 0 and w.cooldown <= 0 and m.energy >= cost:
                    w.cooldown = ws["cooldown"]
                    m.energy -= cost
                    m.last_spend = t
                    self.fire_lightning(m, ws)

    def fire_laser(self, m, w, ws):
        frac = ws["min_frac"] + (1 - ws["min_frac"]) * min(1.0, w.charge / ws["charge"])
        dmg = ws["damage"] * frac * m.dmg_mult
        w.charge = 0.0
        w.full_t = 0.0
        w.cooldown = ws["cooldown"]
        d = self.aim_dir(m.aim[0], m.aim[1])
        o = self.shot_origin(m, self.muzzle(m), d)
        rng_ = ws["range"]
        wall = self.map.ray_wall(o, d, rng_)
        end = [o[0] + d[0] * wall, o[1] + d[1] * wall, o[2] + d[2] * wall]
        hits = []
        for ent, cx, cy, zb, r, h in self.bodies(exclude=m):
            s = self.seg_cyl(o, end, cx, cy, zb, r, h)
            if s is not None:
                hits.append((s, ent))
        hits.sort(key=lambda e: e[0])
        n = 1 + int(ws.get("pierce", 0))
        for s, ent in hits[:n]:
            amt = dmg
            eff = None
            if isinstance(ent, Mech) and ent.holds("mortar"):
                amt *= 1 + ws.get("cookoff", 0.6)
                eff = "cookoff"
            self.damage(ent, amt, "laser", m, m.pos, eff)
        if hits[:n]:
            s = hits[:n][-1][0]
            if n == 1:
                end = [o[0] + (end[0] - o[0]) * s, o[1] + (end[1] - o[1]) * s, o[2] + (end[2] - o[2]) * s]
        self.beams.append((self.t, m.id, "laser", [o, end]))
        self.emit("laser", m.pos, m.id)

    def fire_lightning(self, m, ws):
        o = self.muzzle(m)
        cone = math.radians(ws["cone_deg"]) / 2
        cand = []
        for ent, cx, cy, zb, r, h in self.bodies(exclude=m):
            d = math.hypot(cx - o[0], cy - o[1])
            if d > ws["range"] + r:
                continue
            if abs(wrap(math.atan2(cy - o[1], cx - o[0]) - m.aim[0])) > cone:
                continue
            cand.append((d, ent, (cx, cy, zb + h * 0.5)))
        cand.sort(key=lambda e: e[0])
        path = [o]
        first = None
        for d, ent, c in cand:
            if self.map.los1(o, c):
                first = (ent, c)
                break
        if first is None:
            dd = self.aim_dir(m.aim[0], m.aim[1])
            L = self.map.ray_wall(o, dd, ws["range"])
            path.append([o[0] + dd[0] * L, o[1] + dd[1] * L, o[2] + dd[2] * L])
        else:
            dmg = ws["damage"] * m.dmg_mult
            hit = set()
            ent, c = first
            prev = o
            for jump in range(int(ws["chain"]) + 1):
                hit.add(id(ent))
                path.append(list(c))
                eff = None
                if isinstance(ent, Mech) and ent.holds("laser"):
                    for w in ent.weapons:
                        if w and w.kind == "laser":
                            w.charge = 0.0
                            w.full_t = 0.0
                    ent.short_until = self.t + ws["short_s"]
                    eff = "short"
                self.damage(ent, dmg, "lightning", m, prev, eff)
                dmg *= ws["chain_falloff"]
                prev = c
                nxt = None
                bd = ws["chain_range"]
                for ent2, cx, cy, zb, r, h in self.bodies(exclude=m):
                    if id(ent2) in hit:
                        continue
                    c2 = (cx, cy, zb + h * 0.5)
                    d2 = math.dist(c2, c)
                    if d2 <= bd and self.map.los1(c, c2):
                        nxt, bd = (ent2, c2), d2
                if nxt is None:
                    break
                ent, c = nxt
        self.beams.append((self.t, m.id, "lightning", path))
        self.emit("lightning", m.pos, m.id)

    def explode(self, p, shell):
        ws_m = shell["owner"].wstats["mortar"] if isinstance(shell["owner"], Mech) else self.cfg["weapons"]["mortar"]
        owner = shell["owner"]
        mult = owner.dmg_mult if isinstance(owner, Mech) else 1.0
        R = ws_m["splash_radius"]
        self.emit("explosion", p)
        for ent, cx, cy, zb, r, h in self.bodies():
            cz = min(max(p[2], zb), zb + h)
            d = max(0.0, math.dist((cx, cy, cz), p) - r)
            if d > R:
                continue
            if not self.map.los1(p, (cx, cy, cz + 0.2)):
                continue
            f = 1 - (1 - ws_m["splash_edge"]) * (d / R)
            amt = ws_m["splash"] * f * mult
            if ent is owner:
                amt *= owner.stats["self_damage_mult"]
            eff = None
            if isinstance(ent, Mech):
                eff = "concuss"
                ux, uy = cx - p[0], cy - p[1]
                ul = math.hypot(ux, uy)
                if ul < 1e-6:
                    ux, uy, ul = 1.0, 0.0, 1.0
                ent.vel[0] += ux / ul * ws_m["knock"] * f
                ent.vel[1] += uy / ul * ws_m["knock"] * f
                ent.vel[2] = max(ent.vel[2], 0) + ws_m["knock_up"] * f
                ent.grounded = False
                ent.energy = max(0.0, ent.energy - ws_m["drain"] * f)
                ent.last_spend = self.t
            self.damage(ent, amt, "mortar", owner, p, eff if ent is not owner else None)
            if ent is owner and isinstance(ent, Mech):
                ent.events.append({"type": "effect", "effect": "concuss", "by": ent.id})

    def projectiles_tick(self):
        mp = self.map
        keep = []
        g = self.cfg["weapons"]["mortar"]["gravity"]
        bodies = self.bodies() if self.projectiles else []
        for pr in self.projectiles:
            p0 = pr["pos"]
            if pr["kind"] == "mortar":
                pr["vel"][2] -= g * DT
                pr["ttl"] -= DT
            v = pr["vel"]
            p1 = [p0[0] + v[0] * DT, p0[1] + v[1] * DT, p0[2] + v[2] * DT]
            seg = math.dist(p0, p1)
            if pr["kind"] != "mortar":
                if seg > pr["left"]:
                    f = pr["left"] / seg
                    p1 = [p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f, p0[2] + (p1[2] - p0[2]) * f]
                pr["left"] -= seg
            # wall along the segment
            n = max(1, int(seg / 0.75))
            s_wall = None
            for k in range(1, n + 1):
                s = k / n
                if mp.solid(p0[0] + (p1[0] - p0[0]) * s, p0[1] + (p1[1] - p0[1]) * s, p0[2] + (p1[2] - p0[2]) * s):
                    s_wall = (k - 1) / n
                    break
            if mp.out_of_bounds(p1[0], p1[1]) and s_wall is None:
                s_wall = 1.0
            best = None
            owner = pr["owner"]
            for ent, cx, cy, zb, r, h in bodies:
                if ent is owner:
                    continue
                if pr["kind"] == "npc" and isinstance(ent, NPC):
                    continue
                if abs(cx - p0[0]) > seg + r + 2 and abs(cx - p1[0]) > r + 2:
                    continue
                s = self.seg_cyl(p0, p1, cx, cy, zb, r + pr["r"], h)
                if s is not None and (s_wall is None or s <= s_wall) and (best is None or s < best[0]):
                    best = (s, ent)
            if best is not None:
                s, ent = best
                hp = [p0[0] + (p1[0] - p0[0]) * s, p0[1] + (p1[1] - p0[1]) * s, p0[2] + (p1[2] - p0[2]) * s]
                if pr["kind"] == "mortar":
                    self.damage(ent, pr["dmg"], "mortar", owner, hp)
                    self.explode(hp, pr)
                else:
                    self.damage(ent, pr["dmg"], "npc" if pr["kind"] == "npc" else "gun", owner, p0)
                continue
            if s_wall is not None:
                if pr["kind"] == "mortar":
                    hp = [p0[0] + (p1[0] - p0[0]) * s_wall, p0[1] + (p1[1] - p0[1]) * s_wall,
                          p0[2] + (p1[2] - p0[2]) * s_wall]
                    self.explode(hp, pr)
                continue
            pr["pos"] = p1
            if pr["kind"] == "mortar" and pr["ttl"] <= 0:
                self.explode(p1, pr)
                continue
            if pr["kind"] != "mortar" and pr["left"] <= 0:
                continue
            keep.append(pr)
        self.projectiles = keep

    # ---------------------------------------------------------------- NPCs
    def npc_tick(self):
        nc = self.cfg["npc"]
        mp = self.map
        for n in self.npcs:
            if not n.alive:
                continue
            home_d = math.hypot(n.pos[0] - n.home[0], n.pos[1] - n.home[1])
            tgt = None
            if n.target is not None:
                tm = self.mechs[n.target]
                d = math.hypot(tm.pos[0] - n.pos[0], tm.pos[1] - n.pos[1])
                if not tm.alive or d > nc["deaggro_range"] or home_d > nc["chase_leash"]:
                    n.target = None
                else:
                    tgt = tm
            if tgt is None and home_d <= nc["leash"]:
                best = None
                for m in self.mechs:
                    if not m.alive:
                        continue
                    d = math.hypot(m.pos[0] - n.pos[0], m.pos[1] - n.pos[1])
                    if d <= nc["aggro_range"] and (best is None or d < best[0]):
                        if mp.los1((n.pos[0], n.pos[1], n.pos[2] + 3.0), (m.pos[0], m.pos[1], m.pos[2] + 4.5)):
                            best = (d, m)
                if best:
                    tgt = best[1]
                    n.target = tgt.id
            # movement
            if tgt is not None:
                gx, gy = tgt.pos[0], tgt.pos[1]
                if math.hypot(gx - n.pos[0], gy - n.pos[1]) < 20:
                    gx, gy = n.pos[0], n.pos[1]
            elif home_d > nc["leash"]:
                gx, gy = n.home[0], n.home[1]
            else:
                if n.wander is None or math.hypot(n.wander[0] - n.pos[0], n.wander[1] - n.pos[1]) < 2 or self.rng.random() < 0.004:
                    a = self.rng.uniform(0, TAU)
                    d = self.rng.uniform(0, nc["leash"])
                    n.wander = (n.home[0] + math.cos(a) * d, n.home[1] + math.sin(a) * d)
                gx, gy = n.wander
            dx, dy = gx - n.pos[0], gy - n.pos[1]
            dl = math.hypot(dx, dy)
            if dl > 0.5:
                vx, vy = dx / dl * nc["speed"], dy / dl * nc["speed"]
                nx_, ny_ = n.pos[0] + vx * DT, n.pos[1] + vy * DT
                k = mp.idx(nx_, ny_)
                fl = mp.floor_at(k, n.pos[2] + 1.2)
                if not mp.wall(k, fl + 1.2, fl + nc["height"]) and not mp.out_of_bounds(nx_, ny_):
                    n.pos = [nx_, ny_, fl]
                    n.vel = [vx, vy, 0.0]
                else:
                    n.vel = [0.0, 0.0, 0.0]
                    n.wander = None
            else:
                n.vel = [0.0, 0.0, 0.0]
            # shooting
            if n.cooldown > 0:
                n.cooldown -= DT
            if tgt is not None:
                o = (n.pos[0], n.pos[1], n.pos[2] + 2.5)
                tc = (tgt.pos[0], tgt.pos[1], tgt.pos[2] + tgt.stats["height"] * 0.5)
                yaw = math.atan2(tc[1] - o[1], tc[0] - o[0])
                pit = math.atan2(tc[2] - o[2], math.hypot(tc[0] - o[0], tc[1] - o[1]))
                n.aim = [yaw, pit]
                if n.cooldown <= 0 and mp.los1(o, tc):
                    n.cooldown = nc["cooldown"]
                    sp = math.radians(nc["spread_deg"])
                    d = self.aim_dir(yaw + self.rng.gauss(0, sp), pit + self.rng.gauss(0, sp))
                    o2 = [o[0] + d[0] * 2.3, o[1] + d[1] * 2.3, o[2] + d[2] * 2.3]
                    self.projectiles.append({
                        "id": self._nid("proj"), "kind": "npc", "owner": n, "pos": o2,
                        "vel": [d[0] * nc["projectile_speed"], d[1] * nc["projectile_speed"], d[2] * nc["projectile_speed"]],
                        "left": nc["deaggro_range"] + 10, "dmg": nc["damage"], "r": self.cfg["projectile"]["npc_radius"]})
                    self.emit("npc_gun", n.pos)

    # ---------------------------------------------------------------- cubes, drops, deaths
    def cube_pickups(self):
        R = self.cfg["cubes"]["pickup_radius"]
        for cid in list(self.cubes):
            c = self.cubes[cid]
            best = None
            for m in self.mechs:
                if not m.alive:
                    continue
                d = math.hypot(m.pos[0] - c["pos"][0], m.pos[1] - c["pos"][1])
                if d <= R and abs(m.pos[2] - c["pos"][2]) <= 4 and (best is None or d < best[0]):
                    best = (d, m)
            if best:
                m = best[1]
                del self.cubes[cid]
                self.give_cube(m)
                m.events.append({"type": "pickup", "cubes": m.cubes})

    def drops_tick(self):
        dc = self.cfg["drops"]
        t = self.t
        if self.dropped_called < len(dc["times"]) and t >= dc["times"][self.dropped_called]:
            self.dropped_called += 1
            ph = self.zone_phase(t)
            nc, nr = ph["nc"], ph["nr"]
            p = self.map.random_open(self.rng, nc[0], nc[1], max(nr * dc["spread"], 5))
            if p is None:
                p = [nc[0], nc[1], self.map.ground(nc[0], nc[1])]
            self.drops.append({"id": self._nid("drop"), "pos": p, "lands": t + dc["fall_s"],
                               "progress": 0.0, "holder": None, "landed": False})
        keep = []
        for d in self.drops:
            if t < d["lands"]:
                keep.append(d)
                continue
            if not d["landed"]:
                d["landed"] = True
                self.emit("drop", d["pos"])
            inside = [m for m in self.mechs if m.alive
                      and math.hypot(m.pos[0] - d["pos"][0], m.pos[1] - d["pos"][1]) <= dc["radius"]
                      and abs(m.pos[2] - d["pos"][2]) < 6]
            if len(inside) == 1:
                m = inside[0]
                if d["holder"] != m.id:
                    d["holder"] = m.id
                    d["progress"] = 0.0
                d["progress"] += DT
                if d["progress"] >= dc["capture_s"]:
                    self.give_cube(m, dc["cubes"])
                    if dc.get("repair", 1):
                        m.hp = m.max_hp
                        m.energy = m.stats["energy"]
                    m.events.append({"type": "drop", "id": d["id"], "cubes": m.cubes})
                    continue
            elif not inside:
                d["holder"] = None
                d["progress"] = 0.0
            keep.append(d)
        self.drops = keep

    def deaths(self):
        dying = [m for m in self.mechs if m.alive and m.hp <= 0]
        if not dying:
            return
        alive_before = sum(1 for m in self.mechs if m.alive)
        place = alive_before - len(dying) + 1
        for m in dying:
            m.alive = False
            m.place = place
            m.death_t = self.t
            killer, weapon = getattr(m, "_killer", (None, "zone"))
            m.death_cause = weapon
            if isinstance(killer, Mech) and killer is not m:
                killer.kills += 1
                killer.events.append({"type": "kill", "target": m.id})
            for _ in range(m.cubes + self.cfg["cubes"]["death_drop_extra"]):
                self._spawn_cube(m.pos, 3.0)
            for w in m.weapons:
                if w and w.kind != "gun":
                    w.charge = 0.0
                    self._spawn_pickup(w.kind, [m.pos[0] + self.rng.uniform(-2, 2), m.pos[1] + self.rng.uniform(-2, 2), m.pos[2]], state=w)
            self.emit("death", m.pos)
            self.procs[m.id].send({"type": "end", "place": m.place, "kills": m.kills})

    # ---------------------------------------------------------------- observations
    def build_obs(self, alive):
        cfg = self.cfg
        t = self.t
        vis = cfg["vision"]
        mp = self.map
        nc = cfg["npc"]
        cc = cfg["crates"]
        # candidate pairs that pass range/FOV, then one batched LOS
        others = [("mech", m) for m in self.mechs if m.alive] + [("npc", n) for n in self.npcs if n.alive]
        items = ([("crate", c) for c in self.crates.values()] + [("cube", c) for c in self.cubes.values()]
                 + [("pickup", p) for p in self.pickups.values()])
        # all targets: (kind, entity, x, y, z_center, z_top, owner_id)
        tg = []
        for kind, e in others:
            h = e.stats["height"] if kind == "mech" else nc["height"]
            tg.append((kind, e, e.pos[0], e.pos[1], e.pos[2] + h / 2, e.pos[2] + h - 0.1, e.id if kind == "mech" else -1))
        for kind, e in items:
            h = cc["height"] if kind == "crate" else 0.6
            p = e["pos"]
            tg.append((kind, e, p[0], p[1], p[2] + h / 2, p[2] + h, -1))
        for pr in self.projectiles:
            ow = pr["owner"].id if isinstance(pr["owner"], Mech) else -1
            tg.append(("proj", pr, pr["pos"][0], pr["pos"][1], pr["pos"][2], pr["pos"][2], ow))
        seen = set()
        vis_items = {}
        if tg and alive:
            T = np.array([(x, y, zc) for _, _, x, y, zc, _, _ in tg])
            owner = np.array([o for *_, o in tg])
            E = np.array([(m.pos[0], m.pos[1], m.pos[2] + m.stats["eye_height"]) for m in alive])
            yaw = np.array([m.aim[0] for m in alive])
            near = np.array([vis["near_range"] + m.stats.get("near_range_bonus", 0) for m in alive])
            far = np.array([vis["range"] + m.stats.get("vision_bonus", 0) for m in alive])
            ids = np.array([m.id for m in alive])
            half = math.radians(vis["fov_deg"]) / 2
            DX = T[None, :, 0] - E[:, None, 0]
            DY = T[None, :, 1] - E[:, None, 1]
            DZ = T[None, :, 2] - E[:, None, 2]
            DH = np.hypot(DX, DY)
            ang = np.abs((np.arctan2(DY, DX) - yaw[:, None] + math.pi) % TAU - math.pi)
            mask = (DH <= far[:, None]) & ((np.hypot(DH, DZ) <= near[:, None]) | (ang <= half))
            mask &= owner[None, :] != ids[:, None]
            oi, ti = np.nonzero(mask)
            # static items: cache LOS by observer cell (2 m) so standing/slow mechs don't re-trace
            cache = self.los_cache
            if len(cache) > 200000:
                cache.clear()
            todo_o, todo_t, todo_k = [], [], []
            result = {}
            for a_, b_ in zip(oi.tolist(), ti.tolist()):
                kind = tg[b_][0]
                if kind in ("crate", "cube", "pickup"):
                    m = alive[a_]
                    key = (int(E[a_, 0] // 2), int(E[a_, 1] // 2), int(E[a_, 2] // 2), tg[b_][1]["id"])
                    v = cache.get(key)
                    if v is not None:
                        result[(a_, b_)] = v
                        continue
                    todo_k.append(key)
                else:
                    todo_k.append(None)
                todo_o.append(a_)
                todo_t.append(b_)
            if todo_o:
                A = E[todo_o]
                B = T[todo_t]
                ok = mp.los_batch(A, B, step=1.5)
                redo = [k for k in range(len(todo_o)) if not ok[k] and tg[todo_t[k]][0] in ("mech", "npc", "crate")]
                if redo:
                    B2 = np.array([(tg[todo_t[k]][2], tg[todo_t[k]][3], tg[todo_t[k]][5]) for k in redo])
                    ok2 = mp.los_batch(A[redo], B2, step=1.5)
                    for k, v in zip(redo, ok2):
                        if v:
                            ok[k] = True
                for k in range(len(todo_o)):
                    v = bool(ok[k])
                    result[(todo_o[k], todo_t[k])] = v
                    if todo_k[k] is not None:
                        cache[todo_k[k]] = v
            for (a_, b_), v in result.items():
                if v:
                    m = alive[a_]
                    kind, ent = tg[b_][0], tg[b_][1]
                    if kind in ("mech", "npc"):
                        m.seen[ent.id] = t
                        if kind == "mech":
                            seen.add((m.id, ent.id))
                    else:
                        vis_items.setdefault(m.id, []).append((kind, ent))
        out = {}
        mem = vis["memory_s"]
        hear = cfg["sound"]
        for m in alive:
            mechs_o = []
            for kind, e in others:
                if e is m:
                    continue
                if m.perk_hunt and kind == "mech" and e.perk_hunt:
                    continue
                if t - m.seen.get(e.id, -99) <= mem:
                    if kind == "mech":
                        o = {"id": e.id, "kind": "mech", "pos": [r2(v) for v in e.pos], "vel": [r2(v) for v in e.vel],
                             "aim": [r2(v) for v in e.aim], "cubes": e.cubes,
                             "weapons": [w.kind for w in e.weapons if w], "charging": e.charging()}
                        if vis.get("show_enemy_hp", True):
                            o["hp"] = r2(e.hp)
                            o["max_hp"] = r2(e.max_hp)
                    else:
                        o = {"id": e.id, "kind": "npc", "pos": [r2(v) for v in e.pos], "vel": [r2(v) for v in e.vel],
                             "aim": [r2(v) for v in e.aim]}
                        if vis.get("show_enemy_hp", True):
                            o["hp"] = r2(e.hp)
                            o["max_hp"] = e.max_hp
                    mechs_o.append(o)
            crates_o, cubes_o, picks_o, proj_o = [], [], [], []
            for kind, e in vis_items.get(m.id, ()):
                if kind == "crate":
                    crates_o.append({"id": e["id"], "pos": [r2(v) for v in e["pos"]], "hp": r2(e["hp"])})
                elif kind == "cube":
                    cubes_o.append({"id": e["id"], "pos": [r2(v) for v in e["pos"]]})
                elif kind == "pickup":
                    picks_o.append({"id": e["id"], "kind": e["kind"], "pos": [r2(v) for v in e["pos"]]})
                else:
                    proj_o.append({"id": e["id"], "kind": e["kind"], "pos": [r2(v) for v in e["pos"]],
                                   "vel": [r2(v) for v in e["vel"]]})
            # sounds since the last observation
            sounds_o = []
            noise = math.radians(hear["bearing_noise_deg"]) * m.stats.get("hearing", 1)
            for (st_, kind, sx, sy, src) in self.sounds:
                if st_ <= m.last_obs_t - 1e-9 or src == m.id:
                    continue
                d = math.hypot(sx - m.pos[0], sy - m.pos[1])
                if d > hear["range"].get(kind, 0):
                    continue
                sounds_o.append({"kind": kind, "bearing": r2(wrap(math.atan2(sy - m.pos[1], sx - m.pos[0]) + self.rng.gauss(0, noise))),
                                 "dist": "near" if d < hear["near"] else ("mid" if d < hear["mid"] else "far"),
                                 "age": r2(t - st_)})
            beams_o = []
            for (bt, by, kind, path) in self.beams:
                if bt <= m.last_obs_t - 1e-9 or by == m.id:
                    continue
                if (m.id, by) in seen or any(
                        math.hypot(p[0] - m.pos[0], p[1] - m.pos[1]) < vis["near_range"] for p in path):
                    beams_o.append({"by": by, "kind": kind, "path": [[r2(v) for v in p] for p in path], "age": r2(t - bt)})
            ev = m.events
            if m.zone_dmg > 0:
                ev.append({"type": "damaged", "amount": r2(m.zone_dmg), "weapon": "zone", "bearing": None, "by": None})
                m.zone_dmg = 0.0
            m.events = []
            ph = self.zone_phase(t)
            dps = ph["dps"]
            zone_o = {"center": [r2(ph["c"][0]), r2(ph["c"][1])], "radius": r2(ph["r"]),
                      "next_center": [r2(ph["nc"][0]), r2(ph["nc"][1])], "next_radius": r2(ph["nr"]),
                      "shrink_start": r2(ph["s0"]), "shrink_end": r2(ph["s1"]), "dps": dps}
            if t >= self.phases[-1]["s1"]:
                fc = self.phases[-1]["nc"]
                zone_o.update(center=[r2(fc[0]), r2(fc[1])], radius=0)
            weapons_o = []
            for w in m.weapons:
                if w is None:
                    weapons_o.append(None)
                    continue
                o = {"kind": w.kind, "cooldown": r2(max(w.cooldown, w.equip, 0.0)), "stats": m.wstats[w.kind]}
                if w.kind == "gun":
                    o["ammo"] = w.ammo
                    o["reload"] = r2(max(0.0, w.reload))
                if w.kind == "laser":
                    o["charge"] = r2(w.charge)
                weapons_o.append(o)
            drops_o = [{"id": d["id"], "pos": [r2(v) for v in d["pos"]], "radius": cfg["drops"]["radius"],
                        "lands_in": r2(max(0.0, d["lands"] - t)), "capture_s": cfg["drops"]["capture_s"],
                        "progress": r2(d["progress"]), "holder": d["holder"]} for d in self.drops]
            cx, cy, r, _ = self.zone_circle(t)
            out[m.id] = {
                "type": "obs", "tick": self.tick_n, "t": r2(t), "alive": len(alive),
                "self": {"id": m.id, "pos": [r2(v) for v in m.pos], "vel": [r2(v) for v in m.vel],
                         "aim": [round(v, 3) for v in m.aim], "hp": r2(m.hp), "max_hp": r2(m.max_hp),
                         "energy": r2(m.energy), "max_energy": r2(m.stats["energy"]), "grounded": m.grounded,
                         "cubes": m.cubes, "upgrades": [u for u, n in m.upg.items() for _ in range(n)],
                         "weapons": weapons_o, "in_zone": math.hypot(m.pos[0] - cx, m.pos[1] - cy) <= r,
                         "stats": m.stats},
                "mechs": mechs_o, "projectiles": proj_o, "crates": crates_o, "cubes": cubes_o,
                "pickups": picks_o, "sounds": sounds_o, "beams": beams_o, "events": ev,
                "drops": drops_o, "zone": zone_o, "offer": m.offer,
            }
            m.last_obs_t = t
        # forget old sounds/beams
        cut = t - 1.0
        self.sounds = [s for s in self.sounds if s[0] > cut]
        self.beams = [b for b in self.beams if b[0] > cut]
        return out

    def record_frame(self):
        cx, cy, r, _ = self.zone_circle(self.t)
        self.replay.append({
            "t": self.t, "zone": [r2(cx), r2(cy), r2(r)],
            "mechs": [[m.id, r2(m.pos[0]), r2(m.pos[1]), r2(m.pos[2]), round(m.hp), int(m.alive)] for m in self.mechs],
        })


# ============================================================================ driver

_MAP = None
_CFG = None


def run_match(lineup, seed, budget_ms, log_dir, replay_dir, verbose):
    global _MAP, _CFG
    if _MAP is None:
        _MAP = Map()
        _CFG = load_config()
    replay = [] if replay_dir else None
    match = Match(_CFG, _MAP, lineup, seed, budget_ms, log_dir, replay, verbose)
    res = match.run()
    if replay_dir:
        with open(os.path.join(replay_dir, "match_%d.jsonl" % seed), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"labels": {m.id: m.label for m in match.mechs}, "seed": seed}) + "\n")
            for fr in replay:
                fh.write(json.dumps(fr, separators=(",", ":")) + "\n")
    return res


def parse_lineup(specs):
    lineup = []
    for spec in specs:
        path, _, cnt = spec.rpartition(":")
        if not cnt.isdigit():  # no count given (or a Windows drive letter)
            path, cnt = spec, "1"
        n = int(cnt)
        if not os.path.isfile(path):
            sys.exit("bot not found: %s" % path)
        label = os.path.splitext(os.path.basename(path))[0]
        lineup += [(label, path)] * n
    return lineup


def summarize(results):
    rows = {}
    for res in results:
        for m in res["mechs"]:
            r = rows.setdefault(m["label"], {"n": 0, "points": 0, "place": 0, "wins": 0, "top4": 0, "kills": 0,
                                              "cubes": 0, "surv_t": 0.0, "causes": {}, "missed": 0, "damage": 0})
            r["n"] += 1
            r["points"] += m["points"]
            r["place"] += m["place"]
            r["wins"] += m["place"] == 1
            r["top4"] += m["place"] <= 4
            r["kills"] += m["kills"]
            r["cubes"] += m["cubes"]
            r["damage"] += m["damage"]
            r["missed"] += m["missed"]
            r["surv_t"] += m["death_t"] if m["death_t"] is not None else res["duration"]
            r["causes"][m["cause"]] = r["causes"].get(m["cause"], 0) + 1
    print()
    print("%-16s %5s %7s %6s %6s %6s %6s %6s %7s %6s  %s" % (
        "bot", "n", "points", "place", "win%", "top4%", "kills", "cubes", "dmg", "surv", "how it ended"))
    for label, r in sorted(rows.items(), key=lambda kv: -kv[1]["points"] / kv[1]["n"]):
        n = r["n"]
        causes = ", ".join("%s %d%%" % (k, round(100 * v / n)) for k, v in sorted(r["causes"].items(), key=lambda kv: -kv[1]))
        print("%-16s %5d %7.2f %6.2f %6.1f %6.1f %6.2f %6.2f %7.0f %5.0fs  %s" % (
            label, n, r["points"] / n, r["place"] / n, 100 * r["wins"] / n, 100 * r["top4"] / n,
            r["kills"] / n, r["cubes"] / n, r["damage"] / n, r["surv_t"] / n, causes))
        if r["missed"]:
            print("%-16s       (missed %d decisions in total: too slow or crashed)" % ("", r["missed"]))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bot", action="append", default=[], help="path[:count], repeatable (default: t200.py:8 baseline_bot.py:8)")
    ap.add_argument("--matches", type=int, default=4)
    ap.add_argument("--jobs", type=int, default=0, help="matches in parallel (default: cores/4)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--budget-ms", type=float, default=50.0, help="per-decision answer budget (real server: 50)")
    ap.add_argument("--logs", help="directory for bot stderr logs")
    ap.add_argument("--replay", help="directory for per-match position replays (jsonl)")
    ap.add_argument("--out", help="write all results as JSON here")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    specs = a.bot or [os.path.join(ROOT, "t200.py") + ":8", os.path.join(ROOT, "baseline_bot.py") + ":8"]
    lineup = parse_lineup(specs)
    if len(lineup) > 16:
        sys.exit("at most 16 mechs per match (got %d)" % len(lineup))
    for d in (a.logs, a.replay):
        if d:
            os.makedirs(d, exist_ok=True)
    jobs = a.jobs or max(1, min(a.matches, (os.cpu_count() or 4) // 4))
    print("lineup: %s | %d matches, %d in parallel" % (
        ", ".join("%s x%d" % (l, sum(1 for x in lineup if x[0] == l)) for l in dict.fromkeys(x[0] for x in lineup)),
        a.matches, jobs))
    t0 = time.perf_counter()
    results = []
    seeds = [a.seed + k for k in range(a.matches)]
    if jobs == 1:
        for s in seeds:
            results.append(run_match(lineup, s, a.budget_ms, a.logs, a.replay, a.verbose))
            r = results[-1]
            print("  match %d done in %.0fs (%.0fs of match time)" % (s, r["wall"], r["duration"]))
    else:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            futs = [ex.submit(run_match, lineup, s, a.budget_ms, a.logs, a.replay, a.verbose) for s in seeds]
            for f in as_completed(futs):
                r = f.result()
                results.append(r)
                print("  match %d done in %.0fs (%.0fs of match time)" % (r["seed"], r["wall"], r["duration"]))
    summarize(results)
    print("\n%d matches in %.0fs" % (len(results), time.perf_counter() - t0))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=1)


if __name__ == "__main__":
    main()
