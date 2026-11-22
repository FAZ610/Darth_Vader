"""t8core: the t800 pilot in Python (standard library only).

A port of the decision logic of rogue_agi's pilot (github.com/BrozJosef/mech-royale-rogue-agi,
mech/brain.go + survive.go + ffa.go, MIT), which is built on giddygiddyboy's bot (MIT); the late-game
hide rule comes from SandeepMadhavarapu/BattleRoyale (MIT). Licenses: t800/LICENSE, t800/LICENSE-giddygiddyboy.
The map model is t8world.py. Roof looting (off in rogue_agi) and debug tracing are not ported.

What is ours on top (see t800.py for the submitted profile):
- per-phase parameter overlays (opening / practice squad / free-for-all / end-game hide) and an RNG salt
- `SmartAim`: lead targets with their measured acceleration (t3core smart_aim, rounds 6-7)
- `DropRun` in practice: run for supply drops no known mech is near
- time budgets on every search so a Python decision stays well inside the 50 ms limit
"""
import copy
import math
import os
import random
import sys
import time

import mechfight as mf
import t8world

LAT = 0.075
BUDGET_S = 0.016  # searches stop once a decision has used this much time (limit: 50 ms on 1 CPU)
TAU = 2 * math.pi


def hyp(x, y):
    return math.hypot(x, y)


def ang_diff(a, b):
    d = math.fmod(a - b, TAU)
    if d > math.pi:
        d -= TAU
    elif d < -math.pi:
        d += TAU
    return d


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


class P:
    """Pilot parameters (field names as in rogue_agi's Params)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def copy(self):
        return copy.copy(self)

    def overlay(self, d):
        if d:
            for k, v in d.items():
                if not hasattr(self, k):
                    raise KeyError("unknown t8core param %s" % k)
                setattr(self, k, v)


def default_params():
    return P(RetreatHP=0.38, RecoverHP=0.8, GunRange=85, LightRange=28, LaserRange=85, EngageDist=60, FarmNPC=True,
             Explore=False, Ghost=True, HomeExpo=120, LootRadius=90, CrateUntil=150, UseDrops=False, EndGhost=140,
             Dodge=True, NoMortar=True, Peek=True, LaserFirst=True, CrowdHide=True, Vulture=0, Ambush=0, LaserSeek=0,
             Lethal=False, Alert=0, Shy=0, EarlyHide=0, Evade=False, Odds=0, OddsFlee=0, Practice=True, Stick=0,
             HPw=0, LowBonus=0, MaxTarget=0, LoseRule=False, FightLoot=0, FarmHP=0, AllFoes=False, CubeGoal=0,
             LaserUp=False, Opening=False, NanoUp=False, Finish=0, FinishHP=0, FinishRush=False, Pursue=0,
             FightBoost=0, DodgeBoost=0, ThreatBoost=0, SpeedUp=False, Backstab=0, LethalK=0, Bubble=0,
             BubbleFight=0, EndHide=0, Ambush2=0, LookOut=False, DropRun=0, DropAge=0, SmartAim=False)


def squad_params(p):
    p = p.copy()
    p.Ghost = False
    p.Peek = False
    p.LaserFirst = True
    p.LaserRange = 120
    p.LootRadius = 150
    p.CrateUntil = 1e9
    p.MaxTarget = 240
    p.LoseRule = True
    p.FightLoot = 70
    p.FarmHP = 0.5
    p.LaserSeek = 240
    p.LaserUp = True
    p.Lethal = True
    p.Finish = 20
    p.Stick = 200
    p.LowBonus = 200
    p.LethalK = 0.7
    p.HPw = 0.18
    return p


FFA_TUNING = {"Bubble": 180, "BubbleFight": 50, "UseDrops": True, "EndHide": 60}

UPG = {
    "base": ["plating", "armor", "gun_damage", "nanites", "gun_rate", "lightning_efficiency", "lightning_range",
             "laser_damage", "servos", "laser_charge", "gun_mag", "gun_velocity", "gyros", "lightning_chain", "reactor",
             "capacitor", "mortar_reload", "mortar_splash", "mortar_velocity", "sensors", "jets", "laser_pierce"],
    "laser": ["plating", "armor", "laser_damage", "laser_charge", "nanites", "gun_damage", "gun_rate",
              "lightning_efficiency", "lightning_range", "servos", "gun_mag", "gun_velocity", "gyros",
              "lightning_chain", "reactor", "capacitor", "mortar_reload", "mortar_splash", "mortar_velocity",
              "sensors", "jets", "laser_pierce"],
    "nano": ["plating", "armor", "nanites", "laser_damage", "laser_charge", "gun_damage", "gun_rate",
             "lightning_efficiency", "lightning_range", "servos", "gun_mag", "gun_velocity", "gyros", "lightning_chain",
             "reactor", "capacitor", "mortar_reload", "mortar_splash", "mortar_velocity", "sensors", "jets",
             "laser_pierce"],
    "speed": ["plating", "armor", "servos", "jets", "reactor", "laser_damage", "laser_charge", "nanites",
              "gun_damage", "gun_rate", "lightning_efficiency", "lightning_range", "gun_mag", "gun_velocity", "gyros",
              "lightning_chain", "capacitor", "mortar_reload", "mortar_splash", "mortar_velocity", "sensors",
              "laser_pierce"],
}
WEAPON_RANK = {"lightning": 3, "laser": 2, "mortar": 1}


class Track:
    __slots__ = ("id", "kind", "pos", "vel", "aim", "hp", "max_hp", "cubes", "weapons", "charging", "seen", "hit_me",
                 "dist", "los", "closing", "engage", "acc", "pvel", "pt")

    def __init__(self):
        self.hit_me = -100.0
        self.engage = False
        self.acc = (0.0, 0.0)
        self.pvel = None
        self.pt = -1.0
        self.los = False
        self.closing = 0.0


class Known:
    __slots__ = ("id", "kind", "pos", "hp", "seen")


class WS:
    """Weapon state with stats defaults (missing numbers are 0, as in the Go structs)."""
    __slots__ = ("kind", "cooldown", "ammo", "reload", "charge", "st")

    def __init__(self, d):
        self.kind = d.get("kind", "")
        self.cooldown = d.get("cooldown", 0.0) or 0.0
        self.ammo = d.get("ammo", 0.0) or 0.0
        self.reload = d.get("reload", 0.0) or 0.0
        self.charge = d.get("charge", 0.0) or 0.0
        self.st = d.get("stats") or {}

    def s(self, k):
        return self.st.get(k, 0.0) or 0.0


def has_weapon(ws, kind):
    for i, w in enumerate(ws):
        if w is not None and w.kind == kind:
            return i, w
    return -1, None


class Profile:
    def __init__(self, name="t800", base=None, squad=None, ffa=None, ghost=None, salt=0):
        self.name, self.base, self.squad, self.ffa, self.ghost, self.salt = name, base, squad, ffa, ghost, salt


ACTIVE = Profile()


class Bot:
    name = "t800"

    def __init__(self, hello):
        self.name = ACTIVE.name
        cfg = hello["config"]
        self.cfg = cfg
        self.mech = cfg["mech"]
        self.npc_cfg = cfg.get("npc", {})
        self.crate_cfg = cfg.get("crates", {})
        self.cube_cfg = cfg.get("cubes", {})
        self.loot_cfg = cfg.get("loot", {})
        self.wcfg = cfg.get("weapons", {})
        self.slot = hello.get("slot", 0)
        seed = int(hello.get("seed", 0) or 0)
        if seed == 0:
            seed = self.slot + 1
        self.rng = random.Random(seed + ACTIVE.salt)
        self.W = None
        mdir = (hello.get("map") or {}).get("dir") or "/arena"
        here = os.path.dirname(os.path.abspath(__file__))
        for d in (mdir, "/arena", os.path.join(here, "mechfight-kit", "arena")):
            if os.path.isfile(os.path.join(d, "v2", "world.json")):
                try:
                    self.W = t8world.World(d, os.environ.get("T8_CACHE") or os.path.join(here, "t8cache.pkl"))
                    mf.log("t800 map ready in %.2fs (cached %s)" % (self.W.load_s, self.W.cached))
                except Exception as exc:
                    mf.log("t800 map failed: %r" % (exc,))
                break
        if self.W is None:
            raise RuntimeError("t800 needs the map")
        p = default_params()
        p.overlay(ACTIVE.base)
        self.P = p
        self.base = None
        self.tracks, self.npcs = {}, {}
        self.crates, self.cubes, self.pickups = {}, {}, {}
        self.bad = {}
        self.now = 0.0
        self.path, self.path_goal, self.path_at, self.path_i = None, (0, 0), -100.0, 0
        self.strafe, self.strafe_until = 1.0, 0.0
        self.retreat, self.cover_at, self.cover_goal, self.cover_ok = False, -1.0, (0, 0), False
        self.last_hurt, self.hurt_bearing = -100.0, 0.0
        self.loot_id, self.loot_since = -1, 0.0
        self.hold, self.hold_start = None, None
        self.home_xy, self.home_at, self.home_set = (0.0, 0.0), -100.0, False
        self.explore, self.explore_until = (0.0, 0.0), -1.0
        self.stuck_since, self.unstuck_until, self.unstuck_dir = -1.0, -1.0, (0.0, 0.0)
        self.last_threat_at = -100.0
        self.last_aim = (0.0, 0.0)
        self.esc = None
        self.esc_at, self.esc_flying = -100.0, False
        self.odds_flee_until = 0.0
        self.base_set = self.prac_on = self.end_ghost_on = self.open_on = self.not_practice = False
        self.npc_hurt, self.npc_bearing = 0.0, 0.0
        self.start_alive, self.kills, self.other_dead = 0, 0, 0
        self.stick_id, self.stick_at, self.lose_at = -1, -100.0, 0.0
        self.grab_id, self.grab_since = -1, 0.0
        self.drop_id, self.drop_since, self.drop_landed = -1, 0.0, {}
        self.look_yaw, self.look_at = 0.0, -100.0
        self.ev = {"goal": (0.0, 0.0), "at": -100.0, "ok": False, "hidden": False, "hot": False, "hot_at": -100.0,
                   "set_at": -100.0, "score": 0.0}
        self.deadline = 0.0
        self.mode = "idle"

    # ------------------------------------------------------------------ helpers
    def scale_of(self, cubes):
        return 1 + self.cube_cfg.get("size_per_cube", 0.0) * cubes

    def center(self, t):
        h = self.mech["height"] * self.scale_of(t.cubes)
        if t.kind == "npc":
            h = self.npc_cfg.get("height", 3.0)
        return (t.pos[0], t.pos[1], t.pos[2] + h * 0.5)

    def eye(self, t):
        return (t.pos[0], t.pos[1], t.pos[2] + self.mech["eye_height"] * self.scale_of(t.cubes))

    def busy(self, frac=1.0):
        """True once this decision has used frac of its time budget."""
        return time.perf_counter() > self.t0 + frac * (self.deadline - self.t0)

    # ------------------------------------------------------------------ act
    def act(self, o):
        t0 = time.perf_counter()
        self.t0 = t0
        self.deadline = t0 + BUDGET_S
        act = {"tick": o["tick"], "move": [0.0, 0.0], "boost": False, "fire": [False, False]}
        self.step(o, act)
        a = act.get("aim")
        if a is not None:
            if any(math.isnan(v) or math.isinf(v) for v in a):
                act.pop("aim")
            else:
                self.last_aim = (a[0], a[1])
        if any(math.isnan(v) or math.isinf(v) for v in act["move"]):
            act["move"] = [0.0, 0.0]
        return act

    # ------------------------------------------------------------------ observe
    def observe(self, o, me):
        now = o["t"]
        st = me["stats"]
        mx, my, mz = me["pos"]
        eye = (mx, my, mz + st["eye_height"])
        muzzle = (mx, my, mz + st["muzzle_height"])
        W = self.W
        for m in o.get("mechs", []):
            tab = self.npcs if m.get("kind") == "npc" else self.tracks
            t = tab.get(m["id"])
            if t is None:
                t = Track()
                tab[m["id"]] = t
            vel = m.get("vel") or (0, 0, 0)
            if t.pvel is not None and now - t.pt > 0.05:
                dt = now - t.pt
                ax, ay = (vel[0] - t.pvel[0]) / dt, (vel[1] - t.pvel[1]) / dt
                if dt < 0.35 and hyp(ax, ay) < 80:
                    t.acc = (0.6 * t.acc[0] + 0.4 * ax, 0.6 * t.acc[1] + 0.4 * ay)
                else:
                    t.acc = (0.0, 0.0)
            t.pvel, t.pt = vel, now
            t.id, t.kind, t.pos, t.vel = m["id"], m.get("kind", "mech"), m["pos"], vel
            t.aim = m.get("aim") or (0, 0)
            t.hp, t.max_hp, t.cubes = m.get("hp", 0.0), m.get("max_hp", 0.0), m.get("cubes", 0) or 0
            t.weapons, t.charging = m.get("weapons") or [], bool(m.get("charging"))
            t.seen = now
            dx, dy = t.pos[0] - mx, t.pos[1] - my
            t.dist = hyp(dx, dy)
            if t.dist < 320:
                t.los = W.clear(muzzle, self.center(t))
                if not t.los and t.kind == "mech":
                    h = self.mech["height"] * self.scale_of(t.cubes)
                    t.los = W.clear(muzzle, (t.pos[0], t.pos[1], t.pos[2] + h * 0.85))
            else:
                t.los = False
            if t.dist > 1:
                mv = me["vel"]
                t.closing = -((vel[0] - mv[0]) * dx + (vel[1] - mv[1]) * dy) / t.dist
        for tab, keep in ((self.tracks, 20), (self.npcs, 120)):
            for k in [k for k, t in tab.items() if now - t.seen > keep]:
                del tab[k]

        def upd(tab, items):
            for it in items:
                k = tab.get(it["id"])
                if k is None:
                    k = Known()
                    k.id = it["id"]
                    tab[it["id"]] = k
                k.kind, k.pos, k.hp, k.seen = it.get("kind", ""), it["pos"], it.get("hp", 0.0), now
            for kid in [kid for kid, k in tab.items() if k.seen != now]:
                k = tab[kid]
                if hyp(k.pos[0] - mx, k.pos[1] - my) < 40 and now - k.seen > 0.35 and \
                        W.clear(eye, (k.pos[0], k.pos[1], k.pos[2] + 1.5)):
                    del tab[kid]

        upd(self.crates, o.get("crates", []))
        upd(self.cubes, o.get("cubes", []))
        upd(self.pickups, o.get("pickups", []))
        for e in o.get("events", []):
            et = e.get("type")
            if et == "damaged":
                if e.get("weapon") == "npc" and e.get("bearing") is not None:
                    self.npc_hurt, self.npc_bearing = now, e["bearing"]
                by = e.get("by")
                if by is not None:
                    self.last_hurt = now
                    if e.get("bearing") is not None:
                        self.hurt_bearing = e["bearing"]
                    if by in self.tracks:
                        self.tracks[by].hit_me = now
                    if by in self.npcs:
                        self.npcs[by].hit_me = now
            elif et == "kill":
                self.kills += 1
                self.tracks.pop(e.get("target"), None)

        alive = o.get("alive", 16)
        if not self.base_set:
            self.base, self.base_set = self.P.copy(), True
            self.start_alive = alive
        if self.start_alive - alive - self.kills > 0:
            self.other_dead += 1
        else:
            self.other_dead = 0
        if self.other_dead >= 5 and not self.not_practice:
            # mechs are dying that we did not kill: a free-for-all
            self.not_practice = True
            self.base.overlay(FFA_TUNING)
            self.base.overlay(ACTIVE.ffa)
            self.prac_on = False
            self.P = self.base.copy()
        on = self.base.Practice and not self.not_practice and now > 20
        if on != self.prac_on:
            self.prac_on = on
            self.P = self.base.copy()
            if on:
                self.P = squad_params(self.base)
                self.P.overlay(ACTIVE.squad)
        opening = self.base.Opening and not self.not_practice and not self.prac_on and \
            self.start_alive - alive - self.kills <= 0
        if opening != self.open_on:
            self.open_on = opening
            self.P = self.base.copy()
            if opening:
                self.P.LaserFirst, self.P.LaserSeek, self.P.LootRadius = True, 240, 150
            elif self.prac_on:
                self.P = squad_params(self.base)
                self.P.overlay(ACTIVE.squad)
        z = o["zone"]
        if self.prac_on and not self.end_ghost_on and self.base.EndGhost > 0 and z["next_radius"] <= self.base.EndGhost:
            # practice end game: once the circle is small, stop fighting the squad and hide
            self.end_ghost_on = True
            self.P = self.base.copy()
            self.P.Practice = False
            self.P.overlay(ACTIVE.ghost)
        if self.hold_start != z["shrink_start"]:
            self.hold_start = z["shrink_start"]
            self.hold = (z["center"][0], z["center"][1], z["radius"])
        elif now <= z["shrink_start"]:
            self.hold = (z["center"][0], z["center"][1], z["radius"])

    # ------------------------------------------------------------------ zone
    def zone_at(self, z, t):
        s0, s1 = z["shrink_start"], z["shrink_end"]
        if t <= s0 or s1 <= s0:
            return self.hold
        f = clamp((t - s0) / (s1 - s0), 0, 1)
        hx, hy, hr = self.hold
        nc = z["next_center"]
        return (hx + (nc[0] - hx) * f, hy + (nc[1] - hy) * f, hr + (z["next_radius"] - hr) * f)

    def cur_zone(self, z):
        live = (z["center"][0], z["center"][1], z["radius"])
        if self.now <= z["shrink_start"]:
            return live
        if abs(live[2] - self.hold[2]) > 0.01 or abs(live[0] - self.hold[0]) > 0.01:
            return live
        return self.zone_at(z, self.now)

    def zone_deadline(self, z, x, y, pad):
        nc = z["next_center"]
        if hyp(x - nc[0], y - nc[1]) <= z["next_radius"] - pad:
            return math.inf
        s0, s1 = z["shrink_start"], z["shrink_end"]
        for k in range(25):
            t = s0 + (s1 - s0) * k / 24
            c = self.zone_at(z, t)
            if hyp(x - c[0], y - c[1]) > c[2] - pad:
                return t
        return s1

    def zone_penalty(self, z, x, y):
        c = self.cur_zone(z)
        p = 0.0
        d = hyp(x - c[0], y - c[1]) - c[2]
        if d > -5:
            p += 150 + 5 * (d + 5)
        nc = z["next_center"]
        dn = hyp(x - nc[0], y - nc[1]) - z["next_radius"]
        if dn > -5:
            soon = clamp(1 - (z["shrink_start"] - self.now) / 25, 0.1, 1)
            p += soon * (25 + 0.8 * (dn + 5))
        return p

    def zone_goal(self, z, x, y):
        nr = z["next_radius"]
        nc = z["next_center"]
        margin = clamp(0.3 * nr, 3, 30)
        if nr <= 30:
            return nc[0], nc[1]
        dx, dy = x - nc[0], y - nc[1]
        d = hyp(dx, dy)
        if d < 1:
            return x, y
        r = max(0.0, nr - margin - 5)
        if d <= r:
            return x, y
        return nc[0] + dx / d * r, nc[1] + dy / d * r

    # ------------------------------------------------------------------ upgrades / pickups
    def pick_upgrade(self, offer):
        order = UPG["base"]
        if self.P.LaserUp:
            order = UPG["laser"]
        if self.P.NanoUp:
            order = UPG["nano"]
        if self.P.SpeedUp:
            order = UPG["speed"]
        best, best_rank = 0, 1 << 30
        for i, c in enumerate(offer.get("choices", [])):
            cid = c.get("id") if isinstance(c, dict) else c
            rank = order.index(cid) if cid in order else len(order)
            if rank < best_rank:
                best, best_rank = i, rank
        return best

    def want_pickup(self, ws, kind):
        if kind == "gun":
            return len(ws) > 0 and ws[0] is None
        if has_weapon(ws, kind)[0] >= 0:
            return False
        if kind == "mortar" and self.P.NoMortar:
            return False

        def rank(k):
            if self.P.LaserFirst and k == "laser":
                return 4
            return WEAPON_RANK.get(k, 0)

        cur = rank(ws[1].kind) if len(ws) > 1 and ws[1] is not None else 0
        return rank(kind) > cur

    # ------------------------------------------------------------------ aiming
    def lead(self, muzzle, tp, tv, speed, grounded, acc=(0.0, 0.0)):
        if speed <= 0:
            speed = 252
        t = 0.0
        px = py = pz = 0.0
        for _ in range(4):
            tt = LAT + t
            px, py, pz = tp[0] + tv[0] * tt, tp[1] + tv[1] * tt, tp[2]
            if self.P.SmartAim:
                px += 0.5 * acc[0] * tt * tt
                py += 0.5 * acc[1] * tt * tt
            if not grounded:
                pz += tv[2] * tt * 0.5
            d = math.sqrt((px - muzzle[0]) ** 2 + (py - muzzle[1]) ** 2 + (pz - muzzle[2]) ** 2)
            t = max(0.0, d - 3) / speed
        return math.atan2(py - muzzle[1], px - muzzle[0]), math.atan2(pz - muzzle[2], hyp(px - muzzle[0], py - muzzle[1]))

    def mortar(self, tube, foot, tv, v, g, st):
        if v <= 0 or g <= 0:
            return None
        t = 0.0
        pitch = yaw = 0.0
        for _ in range(3):
            px, py = foot[0] + tv[0] * (LAT + t), foot[1] + tv[1] * (LAT + t)
            dx = hyp(px - tube[0], py - tube[1])
            dz = foot[2] - tube[2]
            disc = v ** 4 - g * (g * dx * dx + 2 * dz * v * v)
            if disc < 0 or dx < 1:
                return None
            pitch = math.atan((v * v - math.sqrt(disc)) / (g * dx))
            yaw = math.atan2(py - tube[1], px - tube[0])
            t = dx / (v * math.cos(pitch))
        if pitch < st["min_pitch"] or pitch > st["max_pitch"]:
            return None
        c, s = math.cos(pitch), math.sin(pitch)
        tt = 0.1
        while tt < t * 0.9:
            d = v * c * tt
            if self.W.solid(tube[0] + math.cos(yaw) * d, tube[1] + math.sin(yaw) * d, tube[2] + v * s * tt - 0.5 * g * tt * tt):
                return None
            tt += 0.1
        return yaw, pitch

    # ------------------------------------------------------------------ dodging
    def dodge_shell(self, o, me):
        mc = self.wcfg.get("mortar", {})
        g = mc.get("gravity", 22) or 22
        rad = (mc.get("splash_radius", 0) or 0) + me["stats"]["radius"] + 2
        mx, my = me["pos"][0], me["pos"][1]
        for p in o.get("projectiles", []):
            if p.get("kind") != "mortar":
                continue
            px, py, pz = p["pos"]
            vx, vy, vz = p["vel"]
            t = 0.0
            while t < 4:
                px += vx * 0.05
                py += vy * 0.05
                pz += vz * 0.05
                vz -= g * 0.05
                if self.W.solid(px, py, pz):
                    d = hyp(px - mx, py - my)
                    if d < rad and t < 2.5:
                        dx, dy = mx - px, my - py
                        if d < 0.5:
                            dx, dy = -vy, vx
                            d = hyp(dx, dy) or 1
                        dx, dy = dx / d, dy / d
                        for rot in (0, 0.7, -0.7, 1.4, -1.4):
                            c, s = math.cos(rot), math.sin(rot)
                            ex, ey = dx * c - dy * s, dx * s + dy * c
                            if self.W.line_walkable(mx, my, mx + ex * 6, my + ey * 6):
                                return ex, ey
                    break
                t += 0.05
        return None

    def dodge(self, o, me):
        st = me["stats"]
        cx, cy, cz = me["pos"][0], me["pos"][1], me["pos"][2] + st["height"] * 0.56
        reach = st["radius"] + 1.1
        dx = dy = 0.0
        laser = False
        for p in o.get("projectiles", []):
            if p.get("kind") == "mortar":
                continue
            vx, vy, vz = p["vel"]
            v2 = vx * vx + vy * vy + vz * vz
            if v2 < 1:
                continue
            px, py, pz = p["pos"]
            tc = ((cx - px) * vx + (cy - py) * vy + (cz - pz) * vz) / v2
            if tc <= 0 or tc > 0.7:
                continue
            mxx, myy = px + vx * tc - cx, py + vy * tc - cy
            if hyp(mxx, myy) < reach:
                vh = hyp(vx, vy)
                if vh < 1:
                    continue
                qx, qy = -vy / vh, vx / vh
                if qx * mxx + qy * myy > 0:
                    qx, qy = -qx, -qy
                dx += qx
                dy += qy
        for m in o.get("mechs", []):
            if m.get("kind") != "mech" or not m.get("charging"):
                continue
            to_me = math.atan2(cy - m["pos"][1], cx - m["pos"][0])
            if abs(ang_diff(m["aim"][0], to_me)) > 0.15:
                continue
            dx += math.cos(to_me + math.pi / 2 * self.strafe) * 1.5
            dy += math.sin(to_me + math.pi / 2 * self.strafe) * 1.5
            laser = True
        l = hyp(dx, dy)
        if l > 0.01:
            return dx / l, dy / l, laser
        return 0.0, 0.0, False

    # ------------------------------------------------------------------ movement
    def travel(self, me, gx, gy):
        x, y = me["pos"][0], me["pos"][1]
        W = self.W
        d = hyp(gx - x, gy - y)
        if d < 0.8:
            return 0.0, 0.0

        def unit(tx, ty):
            l = hyp(tx - x, ty - y)
            if l < 1e-6:
                return 0.0, 0.0
            return (tx - x) / l, (ty - y) / l

        if me["pos"][2] - W.ground_at(x, y) > 3 and W.obst(x, y):
            return unit(gx, gy)
        if d < 45 and W.line_walkable(x, y, gx, gy):
            return unit(gx, gy)
        if self.path is None or hyp(gx - self.path_goal[0], gy - self.path_goal[1]) > 5 or self.now - self.path_at > 2.5:
            budget = clamp(self.deadline - time.perf_counter() - 0.008, 0.002, 0.012)
            self.path, _ = W.path(x, y, gx, gy, 6000, budget)
            self.path_goal = (gx, gy)
            self.path_at = self.now
            self.path_i = 0
        path = self.path
        if not path:
            return unit(gx, gy)
        bi, bd = self.path_i, math.inf
        for i in range(self.path_i, min(len(path), self.path_i + 10)):
            px, py = W.cell_pos(path[i])
            dd = hyp(px - x, py - y)
            if dd < bd:
                bi, bd = i, dd
        self.path_i = bi
        if bd > 12:
            self.path = None
            return unit(gx, gy)
        for i in range(min(bi + 14, len(path) - 1), bi, -1):
            px, py = W.cell_pos(path[i])
            if W.line_walkable(x, y, px, py):
                if i == len(path) - 1 and hyp(px - gx, py - gy) < 4 and W.line_walkable(x, y, gx, gy):
                    return unit(gx, gy)
                return unit(px, py)
        if bi + 1 < len(path):
            return unit(*W.cell_pos(path[bi + 1]))
        return unit(gx, gy)

    def escape(self, me):
        """Stuck off the main walkable area (a roof, a courtyard): jet to the nearest main cell."""
        W = self.W
        x, y, zf = me["pos"]
        if me.get("grounded"):
            if zf - W.ground_at(x, y) > 3 and W.obst(x, y):
                self.esc, self.esc_flying = None, False
                return None
            if not W.off_main(x, y):
                self.esc, self.esc_flying = None, False
                return None
            self.esc_flying = False
            if self.esc is None or self.now - self.esc_at > 6:
                self.esc = W.escape_plan(x, y)
                self.esc_at = self.now
                if self.esc is None:
                    return None
            launch = self.esc[0]
            if hyp(launch[0] - x, launch[1] - y) > 2.5:
                mx, my = self.travel(me, launch[0], launch[1])
                return mx, my, False, False
            if me["energy"] < min(70, me["max_energy"] * 0.7):
                return 0.0, 0.0, False, False
            self.esc_flying = True
            jump = True
        elif not self.esc_flying or self.esc is None:
            return None
        else:
            jump = False
        land = self.esc[1]
        dx, dy = land[0] - x, land[1] - y
        d = hyp(dx, dy)
        if d < 1.5:
            return 0.0, 0.0, False, jump
        mx, my = dx / d, dy / d
        need = -1e9
        t = 0.0
        while t <= min(d, 30):
            need = max(need, W.top_at(x + mx * t, y + my * t))
            t += 1
        return mx, my, zf < need + 2.5 and me["energy"] > 1, jump

    def pref_range(self, ws, energy, t):
        light = has_weapon(ws, "lightning")[1]
        laser = has_weapon(ws, "laser")[1]
        r = self.P.GunRange
        if light is not None and energy > 12:
            r = self.P.LightRange
        elif laser is not None:
            r = self.P.LaserRange
        if t.kind == "npc":
            return 58
        if light is None:
            if "lightning" in t.weapons:
                r = max(r, 64)
            if "mortar" in t.weapons:
                r = max(r, 80)
        return r

    def fight_move(self, o, me, ws, tg, seen, want_los):
        W = self.W
        x, y = me["pos"][0], me["pos"][1]
        st = me["stats"]
        rp = self.pref_range(ws, me["energy"], tg)
        bx, by = tg.pos[0] - x, tg.pos[1] - y
        bd = hyp(bx, by) + 1e-9
        ux, uy = bx / bd, by / bd
        if self.now >= self.strafe_until:
            if self.rng.random() < 0.6:
                self.strafe = -self.strafe
            self.strafe_until = self.now + 0.3 + self.rng.random() * 0.7
        sx, sy = -uy * self.strafe, ux * self.strafe
        tc = self.center(tg)
        mh = st["muzzle_height"]
        cube = None
        cd = math.inf
        for c in self.cubes.values():
            d = hyp(c.pos[0] - x, c.pos[1] - y)
            if d < 40 and d < cd and abs(c.pos[2] - me["pos"][2]) < 4:
                cube, cd = c, d
        others = [e for e in seen if e is not tg]
        best = -math.inf
        mx = my = 0.0
        blocked_side = False
        rings = 2 if self.P.Peek else 1
        z = o["zone"]
        for k in range(-1, 16 * rings):
            cx, cy, dx, dy, r = x, y, 0.0, 0.0, 0.0
            if k >= 0:
                if k >= 16 and self.busy(0.6):
                    break
                a = (k % 16) * math.pi / 8
                r = 6.0 * (1 + k // 16)
                dx, dy = math.cos(a), math.sin(a)
                cx, cy = x + dx * r, y + dy * r
                if not W.line_walkable(x, y, cx, cy) or not W.free(cx, cy):
                    if k < 16 and dx * sx + dy * sy > 0.9:
                        blocked_side = True
                    continue
            cz = W.walk_at(cx, cy)
            d = hyp(tg.pos[0] - cx, tg.pos[1] - cy)
            s = -1.1 * abs(d - rp) - r * 0.4
            los = W.clear((cx, cy, cz + mh), tc)
            if los:
                s += 45 * want_los
            if self.P.Peek and 0 <= k < 16 and los == (want_los > 0) and not self.busy(0.5):
                for q in range(0, 16, 2):
                    qx, qy = cx + math.cos(q * math.pi / 8) * 7, cy + math.sin(q * math.pi / 8) * 7
                    if W.free(qx, qy) and W.clear((qx, qy, W.walk_at(qx, qy) + mh), tc) != los:
                        s += 8
                        break
            body = (cx, cy, cz + st["height"] * 0.6)
            for e in others:
                if hyp(e.pos[0] - cx, e.pos[1] - cy) > 170:
                    continue
                if W.clear(self.eye(e), body):
                    s -= 30
            s -= self.zone_penalty(z, cx, cy)
            if cube is not None:
                s += 1.5 * (hyp(cube.pos[0] - x, cube.pos[1] - y) - hyp(cube.pos[0] - cx, cube.pos[1] - cy))
            cl = W.Clearance[W.cell(cx, cy)]
            if cl < 4:
                s -= (4 - cl) * 2.5
            if want_los > 0:
                s += 9 * (dx * sx + dy * sy)
            if k < 0:
                s -= 8
                if want_los < 0 and not los:
                    s += 14
            if s > best:
                best, mx, my = s, dx, dy
        if blocked_side:
            self.strafe = -self.strafe
            self.strafe_until = self.now + 0.5
        return mx, my

    def cover_move(self, o, me, seen):
        W = self.W
        x, y = me["pos"][0], me["pos"][1]
        st = me["stats"]
        threats = [t for t in seen if hyp(t.pos[0] - x, t.pos[1] - y) < 230]
        if not threats:
            return None
        if len(threats) > 4:
            threats.sort(key=lambda t: hyp(t.pos[0] - x, t.pos[1] - y))
            threats = threats[:4]
        eyes = [self.eye(t) for t in threats]
        h = st["height"]

        def hidden(cx, cy):
            cz = W.walk_at(cx, cy)
            for e in eyes:
                if W.clear(e, (cx, cy, cz + h), 1.5) or W.clear(e, (cx, cy, cz + h * 0.5), 1.5):
                    return False
            return True

        z = o["zone"]
        if self.cover_ok and self.now - self.cover_at < 0.4:
            return self.travel_cover(me)
        self.cover_at = self.now
        if hidden(x, y) and self.zone_penalty(z, x, y) == 0:
            self.cover_ok = True
            self.cover_goal = (x, y)
            return 0.0, 0.0
        s = W.nearest_free(W.cell(x, y))
        if s < 0:
            return None
        best = [-1, math.inf]
        checked = [0]
        NNX = W.NNX

        def visit(c, steps):
            if best[0] >= 0 and steps * 2 > best[1] + 30:
                return False
            if checked[0] >= 350 or self.busy(0.85):
                return False
            ci, cj = c % NNX, c // NNX
            if (ci + cj) % 2 == 0 and steps > 0:
                cx, cy = W.cell_pos(c)
                checked[0] += 1
                if hidden(cx, cy):
                    sc = steps * 2 + self.zone_penalty(z, cx, cy)
                    near = min(hyp(t.pos[0] - cx, t.pos[1] - cy) for t in threats)
                    sc -= min(near, 80) * 0.25
                    if sc < best[1]:
                        best[0], best[1] = c, sc
            return True

        W.bfs(s, visit, max_steps=50)
        if best[0] < 0:
            self.cover_ok = False
            return None
        self.cover_ok = True
        self.cover_goal = W.cell_pos(best[0])
        return self.travel_cover(me)

    def travel_cover(self, me):
        if hyp(self.cover_goal[0] - me["pos"][0], self.cover_goal[1] - me["pos"][1]) < 1.5:
            return 0.0, 0.0
        return self.travel(me, self.cover_goal[0], self.cover_goal[1])

    def hide_from_bearing(self, o, me, seen):
        g = Track()
        g.pos = (me["pos"][0] + math.cos(self.hurt_bearing) * 80, me["pos"][1] + math.sin(self.hurt_bearing) * 80, me["pos"][2])
        g.cubes = 0
        g.kind = "mech"
        return self.cover_move(o, me, [g] + seen)

    # ------------------------------------------------------------------ free-for-all survival layer
    def threats_near(self, me, r, memory):
        return [t for t in self.tracks.values()
                if self.now - t.seen <= memory and hyp(t.pos[0] - me["pos"][0], t.pos[1] - me["pos"][1]) < r]

    def evade_move(self, o, me, threats, hot):
        if not threats:
            return None
        W = self.W
        x, y = me["pos"][0], me["pos"][1]
        st = me["stats"]
        e = self.ev
        path_w, near_w, lat, max_steps = 1.1, 0.55, 4, 85.0
        if self.now - e["at"] > 1:
            e["ok"] = False
        if hot:
            e["hot_at"] = self.now
        elif self.now - e["hot_at"] < 3:
            hot = True
        if hot:
            path_w, near_w, lat, max_steps = 3.0, 0.25, 2, 45.0
        h = st["height"]
        if e["ok"] and e["hidden"] and self.now - e["set_at"] < 4 and hyp(e["goal"][0] - x, e["goal"][1] - y) > 2:
            gx, gy = e["goal"]
            gz = W.walk_at(gx, gy)
            still = True
            for t in threats:
                ey = self.eye(t)
                if W.clear(ey, (gx, gy, gz + h * 0.6)) or W.clear(ey, (gx, gy, gz + h)):
                    still = False
                    break
            if still:
                return self.evade_travel(me)
        if e["ok"] and e["hot"] == hot and self.now - e["at"] < 0.5:
            return self.evade_travel(me)
        if len(threats) > 4:
            threats = sorted(threats, key=lambda t: hyp(t.pos[0] - x, t.pos[1] - y))[:4]
        z = o["zone"]
        nc, nr = z["next_center"], z["next_radius"]
        eyes = [(t, self.eye(t)) for t in threats]

        def score(cx, cy, steps):
            cz = W.walk_at(cx, cy)
            body = (cx, cy, cz + h * 0.6)
            head = (cx, cy, cz + h)
            seen_by = 0
            near = math.inf
            for t, ey in eyes:
                d = hyp(t.pos[0] - cx, t.pos[1] - cy)
                near = min(near, d)
                if d < 260 and (W.clear(ey, body, 1.5) or W.clear(ey, head, 1.5)):
                    seen_by += 1
            s = near_w * min(near, 220) - path_w * steps - self.zone_penalty(z, cx, cy)
            dn = hyp(cx - nc[0], cy - nc[1]) - nr
            if dn > -8:
                soon = clamp(1 - (z["shrink_start"] - self.now) / 30, 0, 1)
                s -= soon * (130 + 2 * (dn + 8))
            if seen_by == 0:
                s += 110
            else:
                s -= 35 * (seen_by - 1)
            cl = W.Clearance[W.cell(cx, cy)]
            if cl < 2:
                s -= (2 - cl) * 8
            elif cl > 7:
                s -= min(cl - 7, 10) * 1.5
            if nr > 80:
                rr = hyp(cx - nc[0], cy - nc[1]) / nr
                if rr < 0.45:
                    s -= (0.45 - rr) * 60
            return s, seen_by == 0

        s0 = W.nearest_free(W.cell(x, y))
        if s0 < 0:
            return None
        here_s, here_h = score(x, y, 0)
        best = [-1, -math.inf, False]
        checked = [0]
        NNX = W.NNX

        def visit(c, steps):
            ci, cj = c % NNX, c // NNX
            if ci % lat == 0 and cj % lat == 0 and steps > 2:
                checked[0] += 1
                if checked[0] >= 480 or self.busy(0.85):
                    return False
                cx, cy = W.cell_pos(c)
                sc, hid = score(cx, cy, steps)
                if sc > best[1]:
                    best[0], best[1], best[2] = c, sc, hid
            return True

        W.bfs(s0, visit, max_steps=max_steps)
        e["at"], e["hot"] = self.now, hot
        best_c, best_s, best_h = best
        if hot and not here_h and (best_c < 0 or not best_h):
            e["ok"] = False
            return None  # exposed under fire with nowhere hidden in reach: fight instead
        if best_c < 0 or (here_s >= best_s - 12 and (here_h or not best_h)):
            e.update(ok=True, hidden=here_h, goal=(x, y), score=here_s)
            return 0.0, 0.0
        gx, gy = W.cell_pos(best_c)
        if e["ok"] and hyp(e["goal"][0] - x, e["goal"][1] - y) > 3:
            cur, _ = score(e["goal"][0], e["goal"][1], hyp(e["goal"][0] - x, e["goal"][1] - y) / 2)
            if cur >= best_s - 20:
                return self.evade_travel(me)
        e.update(ok=True, hidden=best_h, goal=(gx, gy), score=best_s, set_at=self.now)
        return self.evade_travel(me)

    def evade_travel(self, me):
        g = self.ev["goal"]
        if hyp(g[0] - me["pos"][0], g[1] - me["pos"][1]) < 1.5:
            return 0.0, 0.0
        return self.travel(me, g[0], g[1])

    def end_hide(self, o, me):
        if self.P.EndHide <= 0 or o["zone"]["next_radius"] < self.P.EndHide:
            return False
        for t in self.tracks.values():
            if t.seen != self.now or not t.los:
                continue
            if t.hp < 0.7 * me["hp"] or t.hp < 400:
                return False
        return True

    def ambush_ok(self, me, hp_frac, laser):
        if laser is None or laser.cooldown > 0.2 or hp_frac < 0.8:
            return False
        lone = None
        for t in self.tracks.values():
            if self.now - t.seen > 3:
                continue
            if hyp(t.pos[0] - me["pos"][0], t.pos[1] - me["pos"][1]) > 260:
                continue
            if lone is not None or self.now - t.hit_me < 4:
                return False
            lone = t
        if lone is None or lone.seen != self.now or not lone.los:
            return False
        d = hyp(lone.pos[0] - me["pos"][0], lone.pos[1] - me["pos"][1])
        to_me = math.atan2(me["pos"][1] - lone.pos[1], me["pos"][0] - lone.pos[0])
        return 50 < d < self.P.Ambush2 and abs(ang_diff(lone.aim[0], to_me)) > 0.7 and lone.hp <= me["hp"] * 1.1

    def lookout(self, o, me):
        best, best_p = 0.0, -1.0
        for sd in o.get("sounds", []):
            k = sd.get("kind")
            if k in ("step", "boost", "jet", "laser_charge"):
                p = 3
            elif k in ("gun", "laser", "lightning", "mortar"):
                p = 2
            else:
                continue
            p += 2 if sd.get("dist") == "near" else (1 if sd.get("dist") == "mid" else 0)
            if p > best_p:
                best, best_p = sd.get("bearing", 0.0), p
        if best_p >= 0:
            self.look_yaw, self.look_at = best, self.now
            return best
        if self.now - self.look_at < 1.5:
            return self.look_yaw
        near, nd = None, math.inf
        for t in self.tracks.values():
            if self.now - t.seen > 15:
                continue
            d = hyp(t.pos[0] - me["pos"][0], t.pos[1] - me["pos"][1])
            if d < nd and d < 220:
                near, nd = t, d
        if near is None:
            return None
        return math.atan2(near.pos[1] - me["pos"][1], near.pos[0] - me["pos"][0])

    def drop_target(self, o, me, hot):
        x, y = me["pos"][0], me["pos"][1]
        z = o["zone"]
        cur = self.cur_zone(z)
        best, best_d = None, math.inf
        walk = me["stats"]["walk_speed"]
        for d in o.get("drops", []):
            dist = hyp(d["pos"][0] - x, d["pos"][1] - y)
            if dist > self.P.DropRun:
                continue
            if self.bad.get(d["id"], -1) > self.now:
                continue
            if hyp(d["pos"][0] - cur[0], d["pos"][1] - cur[1]) > cur[2] - 10:
                continue
            eta = dist * 1.35 / walk
            if self.now + eta + 6 > self.zone_deadline(z, d["pos"][0], d["pos"][1], 8):
                continue
            lands_in = d.get("lands_in", 0) or 0
            if lands_in > eta + 6:
                continue
            if lands_in <= 0 and d["id"] not in self.drop_landed:
                self.drop_landed[d["id"]] = self.now
            if self.P.DropAge > 0:
                at = self.drop_landed.get(d["id"])
                if at is None or self.now - at < self.P.DropAge:
                    continue
            holder = d.get("holder")
            if holder is not None and holder != me["id"] and (d.get("progress", 0) or 0) > 0.5:
                continue
            inside = dist < 5
            risky = False
            for t in self.tracks.values():
                if self.now - t.seen > 12:
                    continue
                td = hyp(t.pos[0] - d["pos"][0], t.pos[1] - d["pos"][1])
                if td < 110 and not (inside and td > 45):
                    risky = True
                    break
            if risky or (hot and not inside):
                continue
            if dist < best_d:
                best, best_d = d, dist
        if best is None:
            self.drop_id = -1
            return None
        if best["id"] != self.drop_id:
            self.drop_id, self.drop_since = best["id"], self.now
        elif self.now - self.drop_since > 45:
            self.bad[best["id"]] = self.now + 30
            self.drop_id = -1
            return None
        return best

    # ------------------------------------------------------------------ loot / home
    def cube_cap(self):
        c = self.cube_cfg.get("stat_cap", 10)
        return max(c, int(self.P.CubeGoal))

    def choose_loot(self, o, me, ws, hp_frac, danger):
        x, y = me["pos"][0], me["pos"][1]
        z = o["zone"]
        now = self.now
        cur = self.cur_zone(z)
        W = self.W
        walk = me["stats"]["walk_speed"]
        best = [None, 0.0]

        def consider(kind, iid, pos, value):
            if self.bad.get(iid, -1) > now:
                return
            d = hyp(pos[0] - x, pos[1] - y)
            if d > 260:
                return
            if hyp(pos[0] - cur[0], pos[1] - cur[1]) > cur[2] - 6:
                return
            if now + d * 1.4 / walk + 5 > self.zone_deadline(z, pos[0], pos[1], 6):
                return
            if pos[2] - W.ground_at(pos[0], pos[1]) > 3.2:
                return
            nf = W.nearest_free(W.cell(pos[0], pos[1]))
            if nf < 0 or W.Comp[nf] != W.MainComp:
                return
            u = value / (d + 18)
            if iid == self.loot_id:
                u *= 1.35
            if u > best[1]:
                best[0], best[1] = (kind, iid, pos, value), u

        empty1 = len(ws) > 1 and ws[1] is None
        for p in self.pickups.values():
            rad = self.P.LootRadius
            seek = p.kind == "laser" and self.P.LaserSeek > rad
            if seek:
                rad = self.P.LaserSeek
            if self.want_pickup(ws, p.kind) and hyp(p.pos[0] - x, p.pos[1] - y) < rad:
                v = 130.0 if empty1 else 60.0
                if seek:
                    v = max(v, 150.0)
                consider("pickup", p.id, p.pos, v)
        cube_v = 25.0 if me.get("cubes", 0) >= self.cube_cap() else 75.0
        for c in self.cubes.values():
            if hyp(c.pos[0] - x, c.pos[1] - y) < max(60, self.P.LootRadius * 0.7):
                consider("cube", c.id, c.pos, cube_v)
        farm_hp = self.P.FarmHP if self.P.FarmHP > 0 else 0.7
        if hp_frac > farm_hp and not danger and now < self.P.CrateUntil:
            for c in self.crates.values():
                if hyp(c.pos[0] - x, c.pos[1] - y) < self.P.LootRadius:
                    consider("crate", c.id, c.pos, cube_v * 0.6)
            if self.P.FarmNPC and me.get("cubes", 0) < self.cube_cap():
                for n in self.npcs.values():
                    if now - n.seen < 12 and hyp(n.pos[0] - x, n.pos[1] - y) < self.P.LootRadius:
                        consider("npc", n.id, n.pos, 85)
        for d in o.get("drops", []):
            dist = hyp(d["pos"][0] - x, d["pos"][1] - y)
            if self.P.UseDrops and dist / walk < (d.get("lands_in", 0) or 0) + 25 and not danger:
                consider("drop", d["id"], d["pos"], 260)
        b = best[0]
        if b is None:
            self.loot_id = -1
            return None
        if b[1] != self.loot_id:
            self.loot_id = b[1]
            self.loot_since = now
        elif now - self.loot_since > 30:
            self.bad[b[1]] = now + 60
            self.loot_id = -1
            return None
        return b

    def explore_move(self, o, me):
        x, y = me["pos"][0], me["pos"][1]
        z = o["zone"]
        if self.now > self.explore_until or hyp(self.explore[0] - x, self.explore[1] - y) < 6:
            for _ in range(20):
                a = self.rng.random() * TAU
                r = math.sqrt(self.rng.random()) * z["next_radius"] * 0.8
                px, py = z["next_center"][0] + math.cos(a) * r, z["next_center"][1] + math.sin(a) * r
                if not self.W.in_bounds(px, py) or not self.W.free(px, py):
                    continue
                d = hyp(px - x, py - y)
                if d < 50 or d > 220:
                    continue
                self.explore = (px, py)
                self.explore_until = self.now + 30
                break
        if self.now > self.explore_until:
            return 0.0, 0.0
        return self.travel(me, self.explore[0], self.explore[1])

    def home_cost(self, o, px, py):
        z = o["zone"]
        crowd = 0.0
        for t in self.tracks.values():
            if self.now - t.seen < 20:
                crowd += max(0.0, 80 - hyp(t.pos[0] - px, t.pos[1] - py)) / 80
        for d in o.get("drops", []):
            crowd += max(0.0, 60 - hyp(d["pos"][0] - px, d["pos"][1] - py)) / 60
        edge = hyp(px - z["next_center"][0], py - z["next_center"][1]) / max(30, z["next_radius"])
        me = o["self"]
        base = self.P.HomeExpo * self.W.exposure(px, py) + 0.25 * hyp(px - me["pos"][0], py - me["pos"][1]) + 40 * crowd
        if self.P.Bubble > 0:
            return base + 45 * abs(edge - 0.7)  # free-for-all: the middle of the next circle is where mechs die
        return base + 10 * edge

    def home(self, o):
        z = o["zone"]
        nc, nr = z["next_center"], z["next_radius"]
        out = not self.home_set or hyp(self.home_xy[0] - nc[0], self.home_xy[1] - nc[1]) > nr * 0.8
        if out or self.now - self.home_at > 12:
            self.home_at = self.now
            best, best_c = None, math.inf
            for _ in range(40):
                a = self.rng.random() * TAU
                r = math.sqrt(self.rng.random()) * nr * 0.7
                px, py = nc[0] + math.cos(a) * r, nc[1] + math.sin(a) * r
                if not self.W.in_bounds(px, py) or not self.W.reachable(px, py):
                    continue
                c = self.home_cost(o, px, py)
                if c < best_c:
                    best, best_c = (px, py), c
            if best is not None and (out or best_c < self.home_cost(o, self.home_xy[0], self.home_xy[1]) - 15):
                self.home_xy, self.home_set = best, True
        return self.home_xy if self.home_set else None

    def reach(self, ws):
        r = 0.0
        for w in ws:
            if w is None:
                continue
            if w.kind == "gun":
                r = max(r, min(w.s("range") - 10, 130))
            elif w.kind == "laser":
                r = max(r, w.s("range") - 5)
            elif w.kind == "lightning":
                r = max(r, w.s("range"))
        return r

    def odds(self, me, ws, t, now, opening):
        my_w = sum(1 for w in ws if w is not None)
        th_w = len(t.weapons) or 1
        busy_me = busy_them = 0.0
        for u in self.tracks.values():
            if u.id == t.id or now - u.seen > 2.5:
                continue
            if now - u.hit_me < 6:
                busy_me = 1
            br = math.atan2(u.pos[1] - t.pos[1], u.pos[0] - t.pos[0])
            if abs(ang_diff(t.aim[0], br)) < 0.2 and hyp(u.pos[0] - t.pos[0], u.pos[1] - t.pos[1]) < 160:
                busy_them = 1
        z = 1.5093 * math.log(max(me["hp"], 1) / max(t.hp, 1)) + 0.7049 * (min(me.get("cubes", 0), 10) - min(t.cubes, 10)) / 10 + \
            0.9583 * (my_w - th_w) - 0.5592 * (busy_me - busy_them)
        if opening:
            z += 0.0562 + 0.7475 * min(t.dist, 200) / 100
            to_me = math.atan2(me["pos"][1] - t.pos[1], me["pos"][0] - t.pos[0])
            if abs(ang_diff(t.aim[0], to_me)) > 1.75:
                z += 0.8235
        return 1 / (1 + math.exp(-z))

    def shows_back(self, t, x, y):
        arc = self.mech.get("front_arc_deg", 180) or 180
        return abs(ang_diff(t.aim[0], math.atan2(y - t.pos[1], x - t.pos[0]))) > arc * math.pi / 360 + 0.1

    # ------------------------------------------------------------------ the decision
    def step(self, o, act):
        me = o["self"]
        if not me.get("stats") or not me["stats"].get("radius"):
            me["stats"] = self.mech
        self.now = now = o["t"]
        self.observe(o, me)
        P = self.P
        st = me["stats"]
        W = self.W
        x, y, zf = me["pos"]
        z = o["zone"]
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        ws = [WS(w) if w else None for w in me.get("weapons", [])]

        offer = o.get("offer")
        if offer and offer.get("choices"):
            act["pick"] = self.pick_upgrade(offer)

        gun = has_weapon(ws, "gun")[1]
        light = has_weapon(ws, "lightning")[1]
        laser = has_weapon(ws, "laser")[1]
        alive = o.get("alive", 16)
        late = (z["next_radius"] <= 70 and not self.end_ghost_on) or alive <= 3

        seen = []
        target = hidden = shy = None
        best_score = math.inf
        max_t = P.MaxTarget if P.MaxTarget > 0 else 215.0
        hpw = P.HPw if P.HPw > 0 else 60.0 / 1400
        for t in self.tracks.values():
            if now - t.seen > 2.5:
                continue
            t.engage = False
            seen.append(t)
            if t.seen != now:
                t.los = False
                continue
            to_me = math.atan2(y - t.pos[1], x - t.pos[0])
            off = abs(ang_diff(t.aim[0], to_me))
            aimed = off < 0.22
            if P.Ghost:
                t.engage = t.dist < P.EngageDist or now - t.hit_me < 4 or (aimed and t.charging and t.dist < 120) or \
                    (t.hp < 350 and t.dist < 120) or alive <= 2
                if P.Vulture > 0 and hp_frac > 0.75 and t.hp < P.Vulture * t.max_hp and off > 0.6 and t.dist < 165:
                    t.engage = True
                if P.Alert > 0 and t.los and t.dist < P.Alert and (t.closing > 3 or aimed):
                    t.engage = True
                if P.Shy > 0 and t.los and P.EngageDist <= t.dist < P.Shy and (t.closing > 3 or aimed) and not t.engage and \
                        (shy is None or t.dist < shy.dist):
                    shy = t
                if P.Ambush > 0 and hp_frac > 0.85 and off > 1.75 and t.dist < P.Ambush:
                    t.engage = True
                if P.Odds > 0 and not t.engage and t.los and hp_frac > 0.5 and t.dist < self.reach(ws) and \
                        self.odds(me, ws, t, now, True) >= P.Odds:
                    t.engage = True
            elif P.AllFoes and t.dist < max_t:
                t.engage = True
            elif t.dist < P.EngageDist or now - t.hit_me < 6 or late:
                t.engage = True
            elif t.closing > 3 and t.dist < 180:
                t.engage = True
            elif t.hp < 0.4 * t.max_hp and t.dist < 160:
                t.engage = True
            elif aimed and t.dist < 190:
                t.engage = True
            if t.engage and not t.los and t.dist < max_t and (hidden is None or t.dist < hidden.dist):
                hidden = t
            if not t.engage or not t.los or t.dist > max_t:
                continue
            s = t.dist + hpw * t.hp
            if P.LowBonus > 0 and t.hp <= 0.3 * t.max_hp:
                s -= P.LowBonus
            if P.Stick > 0 and t.id == self.stick_id and now - self.stick_at < 2:
                s -= P.Stick
            if P.Backstab > 0 and self.shows_back(t, x, y):
                s -= P.Backstab
            if now - t.hit_me < 4:
                s -= 40
            if t.closing > 3:
                s -= 15
            if s < best_score:
                best_score, target = s, t
        if target is not None:
            self.stick_id, self.stick_at = target.id, now
        foe = target
        if foe is None and P.Peek:
            foe = hidden
        if foe is None and P.Pursue > 0 and hidden is not None and hidden.hp < P.Pursue * hidden.max_hp:
            foe = hidden
        danger = False
        crowd = 0
        for t in seen:
            if t.engage or now - t.hit_me < 4:
                danger = True
            if t.seen == now and (t.engage or (t.los and t.dist < 150)):
                crowd += 1
        if danger or now - self.last_hurt < 3:
            self.last_threat_at = now

        finishing = target is not None and target.dist < 120 and (target.hp < 200 or target.hp < me["hp"] * 0.5)
        outgunned = target is not None and "laser" in target.weapons and laser is None and target.dist > 55 and hp_frac < 0.8
        swamped = P.CrowdHide and (crowd >= 3 or (crowd == 2 and hp_frac < 0.65) or outgunned)
        if P.OddsFlee > 0 and target is not None and not finishing and self.odds(me, ws, target, now, False) < P.OddsFlee:
            self.odds_flee_until = now + 5
        if now < self.odds_flee_until and not finishing:
            swamped = True
        if not self.retreat and ((hp_frac < P.RetreatHP and now - self.last_threat_at < 2) or swamped):
            self.retreat = True
            self.cover_at = -1
        if self.retreat and not swamped and (hp_frac > P.RecoverHP or (now - self.last_threat_at > 7 and hp_frac > 0.55)):
            self.retreat = False
        if P.LoseRule:
            near = sum(1 for t in seen if t.seen == now and t.dist < 160)
            losing = (near >= 2 and hp_frac < 0.55) or (near >= 3 and hp_frac < 0.8)
            if target is not None:
                tf = target.hp / max(1.0, target.max_hp)
                if hp_frac < 0.35 and tf > hp_frac + 0.1:
                    losing = True
                if tf < 0.25 and hp_frac > 0.2 and near <= 2:
                    losing = False
            if losing:
                self.lose_at = now
            self.retreat = now - self.lose_at < 1.5 and self.lose_at > 0

        exposed = any(t.seen == now and t.los and t.dist < 230 for t in seen)
        if any(t.seen == now and t.dist < 45 for t in seen):
            exposed = False

        mx = my = 0.0
        boost = False
        jump = False
        mode = "idle"
        farm = None
        farm_pos = None

        zgx, zgy = self.zone_goal(z, x, y)
        zdist = hyp(zgx - x, zgy - y)
        t_need = zdist * 1.45 / st["walk_speed"] + 4
        deadline = self.zone_deadline(z, x, y, 8)
        zone_must = not me.get("in_zone", True) or now + t_need + 3 >= deadline
        zone_should = now + t_need + 14 >= deadline

        # survival bubble (free-for-all): leave before contact instead of duelling in the open
        ev_threats = []
        grab = None
        ev_hot = False
        if P.Bubble > 0 and (not late or self.end_hide(o, me)) and not finishing:
            close_r = P.BubbleFight if P.BubbleFight > 0 else 32.0
            close_fight = False
            for t in self.tracks.values():
                if now - t.seen > 15:
                    continue
                d = hyp(t.pos[0] - x, t.pos[1] - y)
                vis = t.seen == now and t.los
                if vis and d < close_r:
                    close_fight = True
                if d < P.Bubble or now - t.hit_me < 4:
                    ev_threats.append(t)
                    if (vis and d < 110) or now - t.hit_me < 3:
                        ev_hot = True
                if vis and t.charging and d < 290 and abs(ang_diff(t.aim[0], math.atan2(y - t.pos[1], x - t.pos[0]))) < 0.3:
                    if d >= P.Bubble and now - t.hit_me >= 4:
                        ev_threats.append(t)
                    ev_hot = True
            if close_fight or (P.Ambush2 > 0 and self.ambush_ok(me, hp_frac, laser)):
                ev_threats = []
            if not ev_hot and len(ws) > 1 and ws[1] is None:
                # still unarmed: a nearby weapon no tracked mech is closer to is worth the walk
                bd = 75.0
                for p in self.pickups.values():
                    d = hyp(p.pos[0] - x, p.pos[1] - y)
                    if not self.want_pickup(ws, p.kind) or d >= bd or p.pos[2] - W.ground_at(p.pos[0], p.pos[1]) > 3.2 or \
                            W.off_main(p.pos[0], p.pos[1]):
                        continue
                    if self.bad.get(p.id, -1) > now:
                        continue
                    if self.grab_id != p.id:
                        self.grab_id, self.grab_since = p.id, now
                    elif now - self.grab_since > 8:
                        self.bad[p.id] = now + 60
                        continue
                    if all(hyp(t.pos[0] - p.pos[0], t.pos[1] - p.pos[1]) >= max(60, d + 15) for t in ev_threats):
                        bd = d
                        grab = p.pos

        drop_go = None
        if P.DropRun > 0 and not (zone_must and zdist > 2):
            drop_go = self.drop_target(o, me, ev_hot)

        r = None
        esc = self.escape(me)
        if esc is not None:
            mx, my, boost, jump = esc
            mode = "escape"
        elif now < self.unstuck_until:
            mx, my = self.unstuck_dir
            mode = "unstuck"
        elif (r := self.dodge_shell(o, me)) is not None:
            mx, my = r
            boost = me["energy"] > 15
            mode = "dodge"
        elif zone_must and zdist > 2:
            mx, my = self.travel(me, zgx, zgy)
            boost = (not me.get("in_zone", True) or now + t_need >= deadline) and me["energy"] > 5
            mode = "zone"
        elif drop_go is not None:
            dp = drop_go["pos"]
            if hyp(dp[0] - x, dp[1] - y) < 4.5:
                mx, my = 0.0, 0.0  # inside the ring: hold still until the capture completes
            else:
                mx, my = self.travel(me, dp[0], dp[1])
                boost = me["energy"] > 40
            mode = "drop"
        elif grab is not None:
            mx, my = self.travel(me, grab[0], grab[1])
            mode = "grab"
        elif ev_threats and (r := self.evade_move(o, me, ev_threats, ev_hot)) is not None:
            mx, my = r
            moving = mx != 0 or my != 0
            boost = moving and ev_hot and me["energy"] > 10
            if moving and not ev_hot:
                q = min(1.0, 4.6 / st["walk_speed"])
                mx, my = mx * q, my * q
            mode = "evade"
        elif self.retreat and not finishing and not late:
            r = self.cover_move(o, me, seen)
            if r is not None:
                mx, my = r
                boost = me["energy"] > 10 and (mx != 0 or my != 0)
                mode = "cover"
            elif target is not None:
                mx, my = self.fight_move(o, me, ws, target, seen, 1)
                mode = "cornered"
            else:
                mx, my = self.travel(me, zgx, zgy)
                if self.npc_hurt > 0 and now - self.npc_hurt < 3 and mx == 0 and my == 0:
                    side = -1.0 if math.fmod(now, 3) > 1.5 else 1.0
                    mx, my = -math.sin(self.npc_bearing) * side, math.cos(self.npc_bearing) * side
                mode = "flee"
        elif target is None and now - self.last_hurt < 2.5 and not late and P.Ghost and \
                (r := self.hide_from_bearing(o, me, seen)) is not None:
            mx, my = r
            boost = me["energy"] > 30 and (mx != 0 or my != 0)
            mode = "cover"
        elif now < P.EarlyHide and exposed and not finishing and (r := self.cover_move(o, me, seen)) is not None:
            mx, my = r
            boost = me["energy"] > 20 and (mx != 0 or my != 0)
            mode = "earlyhide"
        elif foe is None and shy is not None and not late and (r := self.cover_move(o, me, seen)) is not None:
            mx, my = r
            boost = me["energy"] > 40 and (mx != 0 or my != 0)
            mode = "shy"
        elif P.Evade and foe is not None and not late and not finishing and foe.dist > P.EngageDist * 1.2 and \
                foe.hp > 0.45 * foe.max_hp and (r := self.cover_move(o, me, seen)) is not None:
            mx, my = r
            boost = me["energy"] > 30 and (mx != 0 or my != 0)
            mode = "evade"
        elif foe is not None:
            ready = gun is not None and gun.ammo > 0 and gun.reload <= 0.25 and foe.dist <= gun.s("range") - 10
            hot = laser is not None and laser.charge >= laser.s("charge") - 0.3 and foe.dist <= laser.s("range") - 5
            if hot or (light is not None and foe.dist <= light.s("range") + 6 and me["energy"] >= light.s("energy") * 3):
                ready = True
            if not P.Peek and (light is not None or laser is not None):
                ready = True
            want_los = 1.0 if ready else -1.0
            if P.Peek and not hot:
                for t in seen:
                    if t.seen == now and t.charging and abs(ang_diff(t.aim[0], math.atan2(y - t.pos[1], x - t.pos[0]))) < 0.3:
                        want_los = -1.6
            fin_hp = P.FinishHP if P.FinishHP > 0 else 0.38
            if P.Finish > 0 and foe.hp < fin_hp * foe.max_hp and hp_frac > 0.42 and crowd <= 2:
                keep = (P.GunRange, P.LaserRange, P.LightRange)
                P.GunRange = P.LaserRange = P.LightRange = P.Finish
                mx, my = self.fight_move(o, me, ws, foe, seen, want_los)
                P.GunRange, P.LaserRange, P.LightRange = keep
                if P.FinishRush and foe.dist > 2 * P.Finish and me["energy"] > 30:
                    boost = True
            else:
                mx, my = self.fight_move(o, me, ws, foe, seen, want_los)
            if light is not None and foe.dist > 50 and me["energy"] > 55 and want_los > 0:
                boost = True
            mode = "fight"
            if P.FightBoost > 0 and me["energy"] > P.FightBoost and (laser is None or laser.charge <= 0) and \
                    (light is None or me["energy"] > 60):
                boost = True
            if P.FightLoot > 0:
                rr = P.FightLoot * (0.57 if hp_frac <= 0.5 else 1.0)
                bc = None
                for c in self.cubes.values():
                    d = hyp(c.pos[0] - x, c.pos[1] - y)
                    if d < rr:
                        rr, bc = d, c.pos
                if bc is not None:
                    mx, my = self.travel(me, bc[0], bc[1])
                    mode = "fight:cube"
        elif zone_should and zdist > 2:
            mx, my = self.travel(me, zgx, zgy)
            mode = "zone"
        else:
            lc = self.choose_loot(o, me, ws, hp_frac, danger)
            if lc is not None:
                kind, lid, lpos, _ = lc
                mode = "loot:" + kind
                if kind == "npc":
                    t = self.npcs.get(lid)
                    if t is not None and now - t.seen < 1 and t.los and t.dist < 75:
                        farm = t
                        mx, my = self.fight_move(o, me, ws, t, seen, 1)
                    else:
                        mx, my = self.travel(me, lpos[0], lpos[1])
                elif kind == "crate":
                    d = hyp(lpos[0] - x, lpos[1] - y)
                    cp = (lpos[0], lpos[1], lpos[2] + self.crate_cfg.get("height", 2.0) * 0.5)
                    if d < 50 and W.clear((x, y, zf + st["muzzle_height"]), cp):
                        farm_pos = cp
                        if d < 12:
                            mx, my = (x - lpos[0]) / max(d, 0.1), (y - lpos[1]) / max(d, 0.1)
                    else:
                        mx, my = self.travel(me, lpos[0], lpos[1])
                else:
                    mx, my = self.travel(me, lpos[0], lpos[1])
                    if kind == "drop" and hyp(lpos[0] - x, lpos[1] - y) < 2.5:
                        mx, my = 0.0, 0.0
            elif zdist > 3 and (not P.Ghost or z["next_radius"] <= 30):
                mx, my = self.travel(me, zgx, zgy)
                mode = "zone-walk"
            elif P.Ghost:
                hm = self.home(o)
                if hm is not None and hyp(hm[0] - x, hm[1] - y) > 3:
                    mx, my = self.travel(me, hm[0], hm[1])
                    if not danger and now - self.last_hurt > 6 and not self.open_on:
                        q = min(1.0, 4.6 / st["walk_speed"])  # quiet: no step sounds below 5 m/s
                        mx, my = mx * q, my * q
                    mode = "home"
            elif P.Explore and not late and me.get("cubes", 0) < self.cube_cap() and hp_frac > 0.7 and not danger:
                mx, my = self.explore_move(o, me)
                mode = "explore"

        if P.Dodge and mode not in ("unstuck", "escape"):
            dx, dy, lz = self.dodge(o, me)
            if dx != 0 or dy != 0:
                mx, my = mx * 0.4 + dx * 0.9, my * 0.4 + dy * 0.9
                l = hyp(mx, my)
                if l > 1:
                    mx, my = mx / l, my / l
                if lz and me["energy"] > 25:
                    boost = True
                if P.DodgeBoost > 0 and me["energy"] > P.DodgeBoost:
                    boost = True
        if P.ThreatBoost > 0 and me["energy"] > P.ThreatBoost and (foe is not None or now - self.last_hurt < 2.5) and \
                (light is None or me["energy"] > 60):
            boost = True

        if mode == "escape":
            self.stuck_since = -1
        elif (mx != 0 or my != 0) and hyp(me["vel"][0], me["vel"][1]) < 1.2 and me.get("grounded"):
            if self.stuck_since < 0:
                self.stuck_since = now
            elif now - self.stuck_since > 0.7:
                a = self.rng.random() * TAU
                self.unstuck_dir = (math.cos(a), math.sin(a))
                self.unstuck_until = now + 0.5
                self.stuck_since = -1
                self.path = None
                jump = True
        else:
            self.stuck_since = -1

        # ---------------------------------------------------------- aiming and firing
        vel = me["vel"]
        muzzle = (x + vel[0] * LAT, y + vel[1] * LAT, zf + st["muzzle_height"])
        aim = [me["aim"][0], 0.0]
        have_aim = False
        tp = tv = None
        tr = th = 0.0
        acc = (0.0, 0.0)
        shootable = is_mech = defend = False
        if target is None and self.npc_hurt > 0 and now - self.npc_hurt < 3:
            worst, best_off = None, 0.7
            for n in self.npcs.values():
                if now - n.seen > 0.5 or not n.los or n.dist > 150:
                    continue
                off = abs(ang_diff(math.atan2(n.pos[1] - y, n.pos[0] - x), self.npc_bearing))
                if now - n.hit_me < 3:
                    off = 0
                if off < best_off:
                    best_off, worst = off, n
            if worst is not None:
                farm, farm_pos, defend = worst, None, True
        if target is not None:
            sc = self.scale_of(target.cubes)
            tr, th = self.mech["radius"] * sc, self.mech["height"] * sc
            tp = [target.pos[0], target.pos[1], target.pos[2] + th * 0.5]
            tv = target.vel
            acc = target.acc
            if not W.clear(muzzle, tp):
                tp[2] = target.pos[2] + th * 0.85
            shootable = is_mech = True
        elif farm is not None:
            tr, th = self.npc_cfg.get("radius", 1.5), self.npc_cfg.get("height", 3.0)
            tp = [farm.pos[0], farm.pos[1], farm.pos[2] + th * 0.5]
            tv = farm.vel
            shootable = True
        elif farm_pos is not None:
            tr, th = self.crate_cfg.get("radius", 1.0), self.crate_cfg.get("height", 2.0)
            tp = list(farm_pos)
            tv = (0.0, 0.0, 0.0)
            shootable = True
        if not is_mech and target is None and (self.retreat or hp_frac < 0.5) and not defend:
            shootable = False

        fire = act["fire"]
        if shootable:
            dist = hyp(tp[0] - x, tp[1] - y)
            grounded = abs(tv[2]) < 0.5
            gy = gp = 0.0
            gun_ok = False
            if gun is not None:
                gy, gp = self.lead(muzzle, tp, tv, gun.s("speed"), grounded, acc)
                gun_ok = dist <= gun.s("range") * 0.96
            dp = (tp[0] + tv[0] * (LAT + 0.05), tp[1] + tv[1] * (LAT + 0.05), tp[2])
            hy = math.atan2(dp[1] - muzzle[1], dp[0] - muzzle[0])
            hpi = math.atan2(dp[2] - muzzle[2], hyp(dp[0] - muzzle[0], dp[1] - muzzle[1]))
            aim = [gy, gp] if gun is not None else [hy, hpi]
            have_aim = True
            tol_y = math.atan2(tr * 0.75, max(dist, 1))
            tol_p = math.atan2(th * 0.4, max(dist, 1))
            turn, pitch_rate = st.get("turn_rate", 3), st.get("pitch_rate", 3)

            def slew(want_y, want_p):
                ey = max(0.0, abs(ang_diff(want_y, me["aim"][0])) - turn * 0.05)
                ep = max(0.0, abs(want_p - me["aim"][1]) - pitch_rate * 0.05)
                return ey < tol_y and ep < tol_p

            for i, w in enumerate(ws[:2]):
                if w is None:
                    continue
                if w.kind == "gun":
                    if gun_ok and w.ammo > 0 and w.reload <= 0 and slew(gy, gp):
                        fire[i] = True
                elif w.kind == "lightning":
                    cone = w.s("cone_deg") * math.pi / 180
                    if dist < w.s("range") - 1.5 and abs(ang_diff(hy, me["aim"][0])) < cone * 0.5 - 0.05 and \
                            me["energy"] >= w.s("energy"):
                        fire[i] = True
                elif w.kind == "laser":
                    if not is_mech or dist > w.s("range") * 0.97:
                        continue
                    full = w.s("charge")
                    if P.Lethal and w.charge >= w.s("min_charge") and w.charge < full - 0.051:
                        frac = w.s("min_frac")
                        dmg = w.s("damage") * (frac + (1 - frac) * w.charge / full) * \
                            (1 + self.cube_cfg.get("damage_per_cube", 0) * min(me.get("cubes", 0), self.cube_cfg.get("stat_cap", 10)))
                        if "mortar" in target.weapons:
                            dmg *= 1 + w.s("cookoff")
                        lk = P.LethalK if P.LethalK > 0 else 0.8
                        if P.Backstab > 0 and self.shows_back(target, x, y):
                            dmg *= self.mech.get("rear_mult", 1) or 1
                        if dmg * lk >= target.hp and abs(ang_diff(hy, me["aim"][0])) < tol_y * 0.9 and abs(hpi - me["aim"][1]) < tol_p:
                            aim = [hy, hpi]
                            fire[i] = False  # release: lethal now
                            continue
                    if w.charge < full - 0.051:
                        fire[i] = True
                        if w.charge > full * 0.45:
                            aim = [hy, hpi]
                    else:
                        aim = [hy, hpi]
                        ey = abs(ang_diff(hy, me["aim"][0]))
                        ep = abs(hpi - me["aim"][1])
                        fire[i] = not (ey < tol_y * 0.9 and ep < tol_p)
                elif w.kind == "mortar":
                    if not is_mech or w.cooldown > 0.25 or dist < 16 or dist > 200:
                        continue
                    tube = (muzzle[0], muzzle[1], zf + st["height"] + 0.5)
                    foot = (tp[0], tp[1], tp[2] - th * 0.5)
                    sol = self.mortar(tube, foot, tv, w.s("speed"), w.s("gravity"), st)
                    if sol is not None:
                        if gun is None or gun.reload > 0 or gun.ammo == 0 or not gun_ok:
                            aim = [sol[0], sol[1]]
                        ey = max(0.0, abs(ang_diff(sol[0], me["aim"][0])) - turn * 0.05)
                        ep = max(0.0, abs(sol[1] - me["aim"][1]) - pitch_rate * 0.05)
                        if ey < 0.04 and ep < 0.03:
                            fire[i] = True

        if target is None and foe is not None:
            # pre-charge the laser for a foe about to come round the corner
            for i, w in enumerate(ws[:2]):
                if w is not None and w.kind == "laser" and w.cooldown <= 0.05 and foe.dist < w.s("range") and \
                        w.charge < w.s("charge") + w.s("hold_s") - 0.35:
                    fire[i] = True

        if not have_aim:
            watch = None
            for t in seen:
                if (t.engage or now - t.hit_me < 6) and (watch is None or t.dist < watch.dist):
                    watch = t
            look = None
            if P.Bubble > 0 and P.LookOut and watch is None:
                look = self.lookout(o, me)
            if watch is not None:
                aim[0] = math.atan2(watch.pos[1] - y, watch.pos[0] - x)
            elif look is not None:
                aim[0] = look
            elif self.npc_hurt > 0 and now - self.npc_hurt < 2.5:
                aim[0] = self.npc_bearing
            elif now - self.last_hurt < 2.5:
                aim[0] = self.hurt_bearing
            elif mx != 0 or my != 0:
                aim[0] = math.atan2(my, mx) + 1.15 * math.sin(now * 1.3)
            else:
                aim[0] = me["aim"][0] + 0.35
            aim[1] = 0.0
        aim[1] = clamp(aim[1], st.get("min_pitch", -0.5), st.get("max_pitch", 0.8))
        act["aim"] = [aim[0], aim[1]]

        if gun is not None and gun.reload <= 0 and gun.ammo < gun.s("mag"):
            if target is None and farm is None and farm_pos is None and \
                    (gun.ammo <= gun.s("mag") * 0.6 or now - self.last_threat_at > 3):
                act["reload"] = True

        slot1 = ws[1].kind if len(ws) > 1 and ws[1] is not None else ""
        pr = self.loot_cfg.get("pickup_radius", 3.0)
        for p in o.get("pickups", []):
            if hyp(p["pos"][0] - x, p["pos"][1] - y) > pr - 0.3 or abs(p["pos"][2] - zf) > 3.6:
                continue
            if not self.want_pickup(ws, p.get("kind", "")):
                continue
            act["take"] = p["id"]
            if slot1 and ws[0] is not None:
                if slot1 == "laser" and ws[1].charge > 0:
                    act.pop("take")
                    break
                act["drop"] = 1
            break

        act["move"] = [mx, my]
        act["boost"] = bool(boost and (mx != 0 or my != 0))
        if jump:
            act["jump"] = True
        self.mode = mode


def main(profile=None):
    global ACTIVE
    if profile is not None:
        ACTIVE = profile
    Bot.name = ACTIVE.name
    mf.run(Bot)


if __name__ == "__main__":
    main()
