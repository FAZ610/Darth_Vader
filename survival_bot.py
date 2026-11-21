import json
import math
import os
import mechfight as mf


def dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def clamp_move(x, y):
    length = math.hypot(x, y)
    if length > 1:
        x /= length
        y /= length
    return [x, y]


def point_in_ring(x, y, ring):
    inside = False
    points = list(zip(ring[0::2], ring[1::2]))
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        if (y1 > y) != (y2 > y):
            cross = (x2 - x1) * (y - y1) / (y2 - y1 + 1e-9) + x1
            if x < cross:
                inside = not inside
    return inside


class Bot:
    name = "survival-cover-py"

    def __init__(self, hello):
        self.config = hello["config"]
        self.pickup_radius = self.config["loot"]["pickup_radius"]
        self.buildings = []
        map_dir = hello["map"]["dir"]
        world_path = os.path.join(map_dir, "v2", "world.json")
        try:
            with open(world_path, "r", encoding="utf-8") as world_file:
                world = json.load(world_file)
            self.buildings = [
                prism for prism in world["prisms"]
                if prism["kind"] == "building"
            ]
        except (OSError, KeyError, json.JSONDecodeError):
            pass

        self.last_enemy_pos = {}
        self.last_enemy_tick = {}

    def building_cover_goal(self, mx, my, enemy_pos):
        candidates = []
        ex, ey = enemy_pos[:2]
        for building in self.buildings:
            ring = building["ring"]
            if len(ring) < 6:
                continue
            xs = ring[0::2]
            ys = ring[1::2]
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            if not (dist2([cx, cy], [mx, my]) < 55):
                continue

            dx, dy = cx - ex, cy - ey
            length = math.hypot(dx, dy)
            if length < 1:
                continue
            dx /= length
            dy /= length

            goal_x = cx + dx * 8
            goal_y = cy + dy * 8
            if point_in_ring(mx, my, ring):
                goal_x, goal_y = cx, cy

            if dist2([goal_x, goal_y], [mx, my]) < 4:
                continue
            candidates.append((dist2([goal_x, goal_y], [mx, my]) +
                               0.25 * dist2([goal_x, goal_y], [ex, ey]),
                               goal_x, goal_y))

        if candidates:
            candidates.sort()
            return candidates[0][1:]
        return None

    def act(self, obs):
        me = obs["self"]
        mx, my, mz = me["pos"]
        tick = obs["tick"]
        act = {"tick": tick}

        if obs["offer"]:
            act["pick"] = 0

        enemies = [m for m in obs["mechs"] if m["kind"] == "mech"]
        for enemy in enemies:
            self.last_enemy_pos[enemy["id"]] = enemy["pos"]
            self.last_enemy_tick[enemy["id"]] = tick

        targets = list(enemies)
        if not targets:
            targets = [
                {"id": enemy_id, "pos": pos}
                for enemy_id, pos in self.last_enemy_pos.items()
                if tick - self.last_enemy_tick.get(enemy_id, tick) <= 50
            ]

        target = min(targets, key=lambda m: dist2(m["pos"], me["pos"])) if targets else None

        zx, zy = obs["zone"]["center"]
        radius = obs["zone"]["radius"]
        dx_zone, dy_zone = zx - mx, zy - my
        zone_distance = math.hypot(dx_zone, dy_zone)
        outside = zone_distance - radius

        if zone_distance > 1:
            ring_goal_x = zx + (mx - zx) / zone_distance * radius * 0.78
            ring_goal_y = zy + (my - zy) / zone_distance * radius * 0.78
        else:
            ring_goal_x = zx + radius * 0.78
            ring_goal_y = zy
        move_x, move_y = ring_goal_x - mx, ring_goal_y - my

        if outside > 5:
            move_x, move_y = dx_zone, dy_zone
        elif target:
            tx, ty, tz = target["pos"]
            dx, dy = tx - mx, ty - my
            distance = math.hypot(dx, dy)
            forward_x = dx / max(distance, 0.001)
            forward_y = dy / max(distance, 0.001)
            side_x, side_y = -forward_y, forward_x

            cover_goal = self.building_cover_goal(mx, my, target["pos"])
            if cover_goal:
                move_x, move_y = cover_goal[0] - mx, cover_goal[1] - my
            elif distance < 52:
                move_x, move_y = -forward_x * 0.55 + side_x * 0.8, \
                                 -forward_y * 0.55 + side_y * 0.8
            elif distance > 100:
                move_x, move_y = forward_x * 0.25, forward_y * 0.25

        # Rotate early to the safe ring instead of rushing the zone center.
        if outside > -8:
            move_x, move_y = dx_zone, dy_zone

        act["move"] = clamp_move(move_x, move_y)
        act["boost"] = bool(me["energy"] > 35 and (
            outside > 0 or (target is not None and dist2(target["pos"], me["pos"]) > 110)
        ))
        act["jump"] = bool(me["grounded"] and (outside > 8 or tick % 90 == 0))

        held = [w for w in me["weapons"] if w is not None]
        held_kinds = {w["kind"] for w in held}
        useful = [
            p for p in obs["pickups"]
            if p["kind"] != "gun"
            and p["kind"] not in held_kinds
            and dist2(p["pos"], me["pos"]) < self.pickup_radius
        ]
        if useful:
            useful.sort(key=lambda p: dist2(p["pos"], me["pos"]))
            act["take"] = useful[0]["id"]

        aim = me["aim"]
        fire = [False, False]
        if target:
            tx, ty, tz = target["pos"]
            dx, dy = tx - mx, ty - my
            horizontal = math.hypot(dx, dy)

            visible = next((m for m in enemies if m["id"] == target["id"]), None)
            vx = vy = 0
            if visible:
                vx, vy = visible.get("vel", [0, 0, 0])[:2]

            gun_speed = 252
            for weapon in me["weapons"]:
                if weapon and weapon["kind"] == "gun":
                    gun_speed = weapon["stats"].get("speed", 252)

            lead = horizontal / gun_speed
            yaw = math.atan2(ty + vy * lead - my, tx + vx * lead - mx)
            pitch = math.atan2(tz + 4.5 - mz - 7, horizontal)
            aim = [yaw, pitch]

            for slot, weapon in enumerate(me["weapons"]):
                if not weapon:
                    continue
                kind = weapon["kind"]
                stats = weapon["stats"]
                if kind == "gun" and weapon["ammo"] > 0 and weapon["reload"] == 0:
                    if horizontal < stats.get("range", 230):
                        fire[slot] = True
                elif kind == "lightning" and horizontal < 45 and me["energy"] >= 3:
                    fire[slot] = True
                elif kind == "laser" and horizontal < stats.get("range", 280):
                    fire[slot] = True
                elif kind == "mortar" and 30 < horizontal < stats.get("range", 235):
                    aim = [yaw, 0.35]
                    fire[slot] = True

        act["aim"] = aim
        act["fire"] = fire
        act["reload"] = False

        mf.draw.point([ring_goal_x, ring_goal_y, mz], "#40c0ff", 5)
        mf.draw.label("survive · hp %.0f · zone %.0f" % (me["hp"], outside))
        return act


mf.run(Bot)
