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
    name = "t100"

    def __init__(self, hello):
        self.config = hello["config"]
        self.pickup_radius = self.config["loot"]["pickup_radius"]
        self.last_enemy_pos = {}
        self.last_enemy_tick = {}

    def choose_upgrade(self, obs):
        offer = obs["offer"]
        me = obs["self"]
        choices = offer["choices"]
        visible_enemies = sum(
            1 for actor in obs["mechs"] if actor["kind"] == "mech"
        )
        low_hp = me["hp"] / me["max_hp"] < 0.55
        low_energy = me["energy"] / me["max_energy"] < 0.35
        outside = not me["in_zone"]
        held = {
            weapon["kind"]
            for weapon in me["weapons"]
            if weapon is not None
        }

        weapon_priority = {
            "mortar": {"mortar_splash", "mortar_reload", "mortar_velocity"},
            "laser": {"laser_charge", "laser_damage", "laser_pierce"},
            "lightning": {
                "lightning_chain",
                "lightning_range",
                "lightning_efficiency",
            },
            "gun": {"gun_damage", "gun_rate", "gun_velocity", "gun_mag"},
        }
        held_priority = set()
        for kind in held:
            held_priority.update(weapon_priority.get(kind, set()))

        scores = []
        for index, choice in enumerate(choices):
            choice_id = choice["id"]
            score = 0

            if low_hp or outside:
                if choice_id in {"plating", "armor"}:
                    score += 100

            if low_energy:
                if choice_id in {"capacitor", "reactor"}:
                    score += 90

            if visible_enemies >= 3:
                if choice_id in {"sensors", "armor", "plating"}:
                    score += 35
                if choice_id in held_priority:
                    score += 30

            if choice_id in held_priority:
                score += 45

            if choice_id in {"gun_damage", "gun_rate"}:
                score += 25

            if not visible_enemies:
                if choice_id in {"sensors", "servos", "nanites", "gyros"}:
                    score += 55
                if choice_id in {"plating", "armor", "reactor"}:
                    score += 20

            if choice_id in {"armor", "plating"}:
                score += 15

            scores.append((score, -index, index))

        return max(scores)[2]

    def act(self, obs):
        me = obs["self"]
        mx, my, mz = me["pos"]
        tick = obs["tick"]
        act = {"tick": tick}

        if obs["offer"]:
            act["pick"] = self.choose_upgrade(obs)

        enemies = [m for m in obs["mechs"] if m["kind"] == "mech"]
        for enemy in enemies:
            self.last_enemy_pos[enemy["id"]] = enemy["pos"]
            self.last_enemy_tick[enemy["id"]] = tick

        targets = list(enemies)
        if not targets:
            targets = [
                {"id": enemy_id, "pos": pos, "kind": "mech"}
                for enemy_id, pos in self.last_enemy_pos.items()
                if tick - self.last_enemy_tick.get(enemy_id, tick) <= 100
            ]

        target = min(
            targets,
            key=lambda enemy: dist2(enemy["pos"], me["pos"]),
        ) if targets else None

        zone = obs["zone"]
        zx, zy = zone["center"]
        zdx, zdy = zx - mx, zy - my
        outside_distance = math.hypot(mx - zx, my - zy) - zone["radius"]
        goal = [mx + zdx, my + zdy]

        move_x, move_y = zdx, zdy
        length = math.hypot(move_x, move_y)
        if length > 0:
            move_x /= length
            move_y /= length

        if target:
            tx, ty, tz = target["pos"]
            dx, dy = tx - mx, ty - my
            distance = math.hypot(dx, dy)
            forward_x = dx / max(distance, 0.001)
            forward_y = dy / max(distance, 0.001)
            side_x, side_y = -forward_y, forward_x

            if distance < 18:
                move_x = -forward_x + side_x * 0.55
                move_y = -forward_y + side_y * 0.55
            elif distance < 55:
                move_x = side_x + forward_x * 0.15
                move_y = side_y + forward_y * 0.15
            else:
                move_x, move_y = forward_x, forward_y

            if outside_distance > -8:
                move_x, move_y = zdx, zdy

        nearby_cubes = sorted(
            obs["cubes"],
            key=lambda cube: dist2(cube["pos"], me["pos"]),
        )
        if nearby_cubes and dist2(
            nearby_cubes[0]["pos"], me["pos"]
        ) < 25:
            cx, cy = nearby_cubes[0]["pos"][:2]
            cube_dx, cube_dy = cx - mx, cy - my

            if target:
                tx, ty, _ = target["pos"]
                enemy_dx, enemy_dy = tx - mx, ty - my
                enemy_distance = math.hypot(enemy_dx, enemy_dy)
                if enemy_distance < 18:
                    # Keep away from an immediate threat; do not move toward loot.
                    move_x, move_y = cube_dx * 0.25 - enemy_dx * 0.75, \
                                     cube_dy * 0.25 - enemy_dy * 0.75
                elif outside_distance > -4:
                    # Zone safety overrides both pursuit and cube collection.
                    move_x, move_y = zdx, zdy
                else:
                    move_x, move_y = cube_dx, cube_dy
            else:
                move_x, move_y = cube_dx, cube_dy

        if outside_distance > -4:
            move_x, move_y = zdx, zdy

        act["move"] = clamp_move(move_x, move_y)
        act["boost"] = bool(
            me["energy"] > 25
            and (
                outside_distance > -5
                or (
                    target is not None
                    and dist2(target["pos"], me["pos"]) > 35
                )
            )
        )
        act["jump"] = bool(
            me["grounded"]
            and (tick % 55 == 0 or outside_distance > 10)
        )

        held = [
            weapon["kind"]
            for weapon in me["weapons"]
            if weapon is not None
        ]
        held_kinds = set(held)
        useful = [
            pickup for pickup in obs["pickups"]
            if pickup["kind"] != "gun"
            and pickup["kind"] not in held_kinds
            and dist2(pickup["pos"], me["pos"]) < self.pickup_radius
        ]
        if useful:
            useful.sort(
                key=lambda pickup: dist2(pickup["pos"], me["pos"])
            )
            act["take"] = useful[0]["id"]

        aim = me["aim"]
        fire = [False, False]

        if target:
            tx, ty, tz = target["pos"]
            dx, dy = tx - mx, ty - my
            horizontal = math.hypot(dx, dy)

            target_actor = next(
                (enemy for enemy in enemies if enemy["id"] == target["id"]),
                None,
            )
            vx = vy = vz = 0
            if target_actor:
                vx, vy, vz = target_actor.get("vel", [0, 0, 0])

            gun_speed = None
            for weapon in me["weapons"]:
                if weapon and weapon["kind"] == "gun":
                    gun_speed = weapon["stats"].get("speed")

            flight_time = (
                horizontal / gun_speed if gun_speed else 0
            )
            predicted_x = tx + vx * flight_time
            predicted_y = ty + vy * flight_time
            yaw = math.atan2(
                predicted_y - my,
                predicted_x - mx,
            )
            pitch = math.atan2(
                tz + 4.5 - mz - 7,
                horizontal,
            )
            aim = [yaw, pitch]

            for slot, weapon in enumerate(me["weapons"]):
                if not weapon:
                    continue

                kind = weapon["kind"]
                stats = weapon["stats"]
                if (
                    kind == "gun"
                    and weapon["ammo"] > 0
                    and weapon["reload"] == 0
                ):
                    if horizontal < stats.get("range", 230):
                        fire[slot] = True
                elif (
                    kind == "lightning"
                    and horizontal < 45
                    and me["energy"] >= 3
                ):
                    fire[slot] = True
                elif kind == "laser":
                    charge = weapon.get("charge", 0)
                    if charge == 0:
                        if horizontal < stats.get("range", 280):
                            fire[slot] = True
                    elif charge >= stats.get("charge", 0.75):
                        fire[slot] = False
                elif (
                    kind == "mortar"
                    and 18 < horizontal < stats.get("range", 235)
                ):
                    aim = [yaw, 0.35]
                    fire[slot] = True

        act["aim"] = aim
        act["fire"] = fire
        act["reload"] = False

        mf.draw.point([goal[0], goal[1], mz], "#40c0ff", 5)
        mf.draw.label(
            "t100 · hp %.0f · zone %.0f"
            % (me["hp"], outside_distance)
        )
        return act


mf.run(Bot)
