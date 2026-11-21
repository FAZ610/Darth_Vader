import math
import mechfight as mf


def dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def clamp_move(x, y):
    length = math.hypot(x, y)
    if length > 1:
        x /= length
        y /= length
    return [x, y]


class Bot:
    name = "baseline-py"

    def __init__(self, hello):
        self.config = hello["config"]
        self.pickup_radius = self.config["loot"]["pickup_radius"]
        self.last_enemy_pos = {}
        self.last_enemy_tick = {}

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

        # Visible enemies have priority. Otherwise keep the most recent enemy location briefly.
        targets = []
        for enemy in enemies:
            targets.append(enemy)
        if not targets:
            for enemy_id, pos in list(self.last_enemy_pos.items()):
                if tick - self.last_enemy_tick.get(enemy_id, tick) > 100:
                    continue
                targets.append({"id": enemy_id, "pos": pos, "kind": "mech"})

        target = min(targets, key=lambda m: dist2(m["pos"], me["pos"])) if targets else None

        zone = obs["zone"]
        zx, zy = zone["center"]
        zdx, zdy = zx - mx, zy - my
        in_zone = me["in_zone"]
        outside_distance = math.hypot(mx - zx, my - zy) - zone["radius"]
        goal = [mx + zdx, my + zdy]

        move_x, move_y = zdx, zdy
        length = math.hypot(move_x, move_y)
        if length > 0:
            move_x /= length
            move_y /= length

        # Kite and strafe near a target; approach distant targets.
        if target:
            tx, ty, tz = target["pos"]
            dx, dy = tx - mx, ty - my
            distance = math.hypot(dx, dy)
            forward_x, forward_y = dx / max(distance, 0.001), dy / max(distance, 0.001)
            side_x, side_y = -forward_y, forward_x
            if distance < 18:
                move_x, move_y = -forward_x + side_x * 0.55, -forward_y + side_y * 0.55
            elif distance < 55:
                move_x, move_y = side_x + forward_x * 0.15, side_y + forward_y * 0.15
            else:
                move_x, move_y = forward_x, forward_y

            # Zone safety overrides chasing once outside the circle.
            if outside_distance > -8:
                move_x, move_y = zdx, zdy

        # Nearby cubes are useful while there is no immediate fight.
        if not target or len(enemies) == 0:
            nearby_cubes = sorted(
                obs["cubes"],
                key=lambda c: dist2(c["pos"], me["pos"]),
            )
            if nearby_cubes and dist2(nearby_cubes[0]["pos"], me["pos"]) < 25:
                cx, cy = nearby_cubes[0]["pos"][:2]
                move_x, move_y = cx - mx, cy - my

        # Exit movement is the zone direction when the bot is outside or close to its edge.
        if outside_distance > -4:
            move_x, move_y = zdx, zdy

        act["move"] = clamp_move(move_x, move_y)
        act["boost"] = bool(
            me["energy"] > 25
            and (
                outside_distance > -5
                or (target is not None and dist2(target["pos"], me["pos"]) > 35)
            )
        )

        # Jump over short obstacles or periodically to make gun shots harder to land.
        act["jump"] = me["grounded"] and (tick % 55 == 0 or outside_distance > 10)

        # Take a useful pickup into an empty slot. Prefer a weapon not already held.
        held = [w for w in me["weapons"] if w is not None]
        held_kinds = {w["kind"] for w in held}
        useful = [p for p in obs["pickups"]
                  if p["kind"] != "gun" and p["kind"] not in held_kinds
                  and dist2(p["pos"], me["pos"]) < self.pickup_radius]
        if useful:
            useful.sort(key=lambda p: dist2(p["pos"], me["pos"]))
            act["take"] = useful[0]["id"]

        aim = me["aim"]
        fire = [False, False]

        if target:
            tx, ty, tz = target["pos"]
            dx, dy = tx - mx, ty - my
            horizontal = math.hypot(dx, dy)

            # Lead gun and laser targets using their visible velocity.
            target_actor = next((m for m in enemies if m["id"] == target["id"]), None)
            vx = vy = vz = 0
            if target_actor:
                vx, vy, vz = target_actor.get("vel", [0, 0, 0])

            gun_speed = None
            for weapon in me["weapons"]:
                if weapon and weapon["kind"] == "gun":
                    gun_speed = weapon["stats"].get("speed")
            flight_time = horizontal / gun_speed if gun_speed else 0
            predicted_x = tx + vx * flight_time
            predicted_y = ty + vy * flight_time

            yaw = math.atan2(predicted_y - my, predicted_x - mx)
            pitch = math.atan2(tz + 4.5 - mz - 7, horizontal)
            aim = [yaw, pitch]

            for slot, weapon in enumerate(me["weapons"]):
                if not weapon:
                    continue
                kind = weapon["kind"]
                if kind == "gun" and weapon["ammo"] > 0 and weapon["reload"] == 0:
                    if horizontal < weapon["stats"].get("range", 230):
                        fire[slot] = True
                elif kind == "lightning" and horizontal < 45 and me["energy"] >= 3:
                    fire[slot] = True
                elif kind == "laser":
                    charge = weapon.get("charge", 0)
                    stats = weapon["stats"]
                    if charge == 0:
                        if horizontal < stats.get("range", 280):
                            fire[slot] = True
                    elif charge >= stats.get("charge", 0.75):
                        fire[slot] = False
                elif kind == "mortar" and 18 < horizontal < weapon["stats"].get("range", 235):
                    aim = [yaw, 0.35]
                    fire[slot] = True

        act["aim"] = aim
        act["fire"] = fire
        act["reload"] = False

        mf.draw.point([goal[0], goal[1], mz], "#40c0ff", 5)
        mf.draw.label("baseline · hp %.0f · zone %.0f" %
                      (me["hp"], outside_distance))
        return act


mf.run(Bot)
