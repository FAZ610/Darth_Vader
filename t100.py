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
        self.pickup_radius = 4
        self.last_enemy_pos = {}
        self.last_enemy_tick = {}

    def choose_upgrade(self, obs):
        offer = obs["offer"]
        me = obs["self"]
        visible = [m for m in obs["mechs"] if m["kind"] == "mech"]
        held = {
            w["kind"] for w in me["weapons"] if w is not None
        }

        weapon_upgrades = {
            "mortar": {"mortar_splash", "mortar_reload", "mortar_velocity"},
            "laser": {"laser_charge", "laser_damage", "laser_pierce"},
            "lightning": {
                "lightning_chain",
                "lightning_range",
                "lightning_efficiency",
            },
            "gun": {"gun_damage", "gun_rate", "gun_velocity", "gun_mag"},
        }
        held_weapon_ids = set()
        for kind in held:
            held_weapon_ids.update(weapon_upgrades.get(kind, set()))

        scores = []
        for index, choice in enumerate(offer["choices"]):
            choice_id = choice["id"]
            score = 0

            if me["hp"] / me["max_hp"] < 0.55 or not me["in_zone"]:
                if choice_id in {"plating", "armor"}:
                    score += 140

            if me["energy"] / me["max_energy"] < 0.35:
                if choice_id in {"capacitor", "reactor", "jets"}:
                    score += 100

            if choice_id in held_weapon_ids:
                score += 70
            if choice_id in {"gun_damage", "gun_rate", "gun_velocity", "gun_mag"}:
                score += 45
            if choice_id in {"armor", "plating", "nanites"}:
                score += 35
            if choice_id in {"sensors", "gyros", "servos"}:
                score += 30

            if len(visible) >= 3:
                if choice_id in {"armor", "plating", "sensors"}:
                    score += 45

            if not visible:
                if choice_id in {"sensors", "servos", "gyros", "nanites"}:
                    score += 40

            scores.append((score, -index, index))

        return max(scores)[2]

    def act(self, obs):
        me = obs["self"]
        mx, my, mz = me["pos"]
        tick = obs["tick"]
        act = {"tick": tick}

        if obs["offer"]:
            act["pick"] = self.choose_upgrade(obs)

        zone = obs["zone"]
        zx, zy = zone["center"]
        zone_dx, zone_dy = zx - mx, zy - my
        zone_distance = math.hypot(zone_dx, zone_dy)
        outside_distance = zone_distance - zone["radius"]

        goal_x, goal_y = zx, zy
        move_x, move_y = zone_dx, zone_dy

        actors = [m for m in obs["mechs"] if m["kind"] == "mech"]
        npcs = [m for m in obs["mechs"] if m["kind"] == "npc"]

        for enemy in actors:
            self.last_enemy_pos[enemy["id"]] = enemy["pos"]
            self.last_enemy_tick[enemy["id"]] = tick

        enemies = list(actors)
        if not enemies:
            enemies = [
                {"id": enemy_id, "pos": pos, "kind": "mech"}
                for enemy_id, pos in self.last_enemy_pos.items()
                if tick - self.last_enemy_tick.get(enemy_id, tick) <= 100
            ]

        target = min(
            enemies,
            key=lambda enemy: dist2(enemy["pos"], me["pos"]),
        ) if enemies else None

        # NPC drones shoot within 45 m. Treat them as immediate threats:
        # break off, move away, and do not chase loot in their radius.
        npc_threat = None
        npc_threat_distance = 999
        for npc in npcs:
            distance = dist2(npc["pos"], me["pos"])
            if distance < npc_threat_distance:
                npc_threat_distance = distance
                npc_threat = npc

        if npc_threat is not None and npc_threat_distance < 55:
            nx, ny = npc_threat["pos"][:2]
            dx, dy = mx - nx, my - ny
            length = math.hypot(dx, dy)
            if length > 0:
                dx /= length
                dy /= length
            move_x, move_y = dx, dy
        else:
            # 1. Weapon pickup: replace a gun first; search for a stronger
            # mortar, laser, or lightning.
            held = [
                w for w in me["weapons"] if w is not None
            ]
            held_kinds = {w["kind"] for w in held}
            useful_pickups = [
                p for p in obs["pickups"]
                if p["kind"] != "gun"
                and p["kind"] not in held_kinds
            ]

            weapon_target = None
            if useful_pickups:
                useful_pickups.sort(
                    key=lambda p: dist2(p["pos"], me["pos"])
                )
                for pickup in useful_pickups:
                    distance = dist2(pickup["pos"], me["pos"])
                    # Do not chase loot far away or outside the safe zone.
                    if distance < 80:
                        px, py = pickup["pos"][:2]
                        if math.hypot(px - zx, py - zy) <= zone["radius"] + 8:
                            weapon_target = pickup
                            break

            # 2. Cubes provide +4% max HP and +4% damage until 10 cubes.
            # Preserve stronger choices and never route to them outside combat.
            cube_target = None
            if obs["cubes"] and me["cubes"] < 10:
                nearest_cubes = sorted(
                    obs["cubes"],
                    key=lambda c: dist2(c["pos"], me["pos"]),
                )
                for cube in nearest_cubes:
                    distance = dist2(cube["pos"], me["pos"])
                    cx, cy = cube["pos"][:2]
                    if (
                        distance < 70
                        and math.hypot(cx - zx, cy - zy)
                        <= zone["radius"] + 8
                    ):
                        cube_target = cube
                        break

            # 3. Capturable supply drops. Only approach once landed,
            # stay in the ring, and prefer drops near the zone.
            supply_target = None
            for drop in obs["drops"]:
                if drop["lands_in"] == 0:
                    dx = drop["pos"][0] - mx
                    dy = drop["pos"][1] - my
                    distance = math.hypot(dx, dy)
                    if distance < 75:
                        px, py = drop["pos"][:2]
                        if math.hypot(px - zx, py - zy) <= zone["radius"] + 8:
                            supply_target = drop
                            break

            # 4. Nearby crates: destroy them to obtain cubes and a chance
            # of weapon loot, but do not leave the zone for this.
            crate_target = None
            if obs["crates"]:
                nearest_crates = sorted(
                    obs["crates"],
                    key=lambda c: dist2(c["pos"], me["pos"]),
                )
                for crate in nearest_crates:
                    distance = dist2(crate["pos"], me["pos"])
                    cx, cy = crate["pos"][:2]
                    if (
                        distance < 50
                        and math.hypot(cx - zx, cy - zy)
                        <= zone["radius"] + 8
                    ):
                        crate_target = crate
                        break

            if weapon_target is not None:
                goal_x, goal_y = weapon_target["pos"][:2]
                move_x, move_y = goal_x - mx, goal_y - my
            elif cube_target is not None:
                goal_x, goal_y = cube_target["pos"][:2]
                move_x, move_y = goal_x - mx, goal_y - my
            elif supply_target is not None:
                goal_x, goal_y = supply_target["pos"][:2]
                move_x, move_y = goal_x - mx, goal_y - my
            elif crate_target is not None:
                goal_x, goal_y = crate_target["pos"][:2]
                move_x, move_y = goal_x - mx, goal_y - my

            # Combat movement remains a kiting/strafing behavior.
            if target:
                tx, ty, _ = target["pos"]
                dx, dy = tx - mx, ty - my
                distance = math.hypot(dx, dy)
                forward_x = dx / max(distance, 0.001)
                forward_y = dy / max(distance, 0.001)
                side_x, side_y = -forward_y, forward_x

                if distance < 18:
                    combat_move_x = -forward_x + side_x * 0.55
                    combat_move_y = -forward_y + side_y * 0.55
                elif distance < 55:
                    combat_move_x = side_x + forward_x * 0.15
                    combat_move_y = side_y + forward_y * 0.15
                else:
                    combat_move_x, combat_move_y = forward_x, forward_y

                if distance < 110:
                    move_x, move_y = combat_move_x, combat_move_y

        # Zone safety is absolute and overrides loot, crates, drops, and combat.
        if outside_distance > -4:
            goal_x, goal_y = zx, zy
            move_x, move_y = zone_dx, zone_dy

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

        held = [w for w in me["weapons"] if w is not None]
        held_kinds = {w["kind"] for w in held}

        # Take a stronger weapon. With no empty slot, swap only if the gun
        # is present, leaving the gun on the ground.
        useful = [
            p for p in obs["pickups"]
            if p["kind"] != "gun"
            and p["kind"] not in held_kinds
        ]
        if useful:
            useful.sort(key=lambda p: dist2(p["pos"], me["pos"]))
            pickup = useful[0]
            if dist2(pickup["pos"], me["pos"]) <= self.pickup_radius:
                if len(held) < 2:
                    act["take"] = pickup["id"]
                elif len(me["weapons"]) == 2:
                    for slot, weapon in enumerate(me["weapons"]):
                        if weapon is not None and weapon["kind"] == "gun":
                            act["take"] = pickup["id"]
                            act["drop"] = slot
                            break

        aim = me["aim"]
        fire = [False, False]

        visible_target = target if target and "kind" in target and target["id"] in {
            a["id"] for a in actors
        } else None
        if visible_target:
            tx, ty, tz = visible_target["pos"]
            dx, dy = tx - mx, ty - my
            horizontal = math.hypot(dx, dy)

            target_actor = next(
                (enemy for enemy in actors if enemy["id"] == visible_target["id"]),
                None,
            )
            vx = vy = vz = 0
            if target_actor:
                vx, vy, vz = target_actor.get("vel", [0, 0, 0])

            gun_speed = None
            for weapon in me["weapons"]:
                if weapon and weapon["kind"] == "gun":
                    gun_speed = weapon["stats"].get("speed")

            lead = horizontal / gun_speed if gun_speed else 0
            yaw = math.atan2(
                ty + vy * lead - my,
                tx + vx * lead - mx,
            )
            pitch = math.atan2(tz + 4.5 - mz - 7, horizontal)
            aim = [yaw, pitch]
        elif crate_target if "crate_target" in locals() else False:
            tx, ty, tz = crate_target["pos"]
            dx, dy = tx - mx, ty - my
            horizontal = math.hypot(dx, dy)
            yaw = math.atan2(ty - my, tx - mx)
            aim = [yaw, math.atan2(tz - mz - 7, horizontal)]

        if visible_target:
            tx, ty, tz = visible_target["pos"]
            dx, dy = tx - mx, ty - my
            horizontal = math.hypot(dx, dy)

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
                elif kind == "laser":
                    charge = weapon.get("charge", 0)
                    if horizontal < stats.get("range", 280):
                        if charge == 0:
                            fire[slot] = True
                elif kind == "mortar" and 18 < horizontal < stats.get("range", 235):
                    aim = [math.atan2(ty - my, tx - mx), 0.35]
                    fire[slot] = True
        elif crate_target if "crate_target" in locals() else False:
            tx, ty, _ = crate_target["pos"]
            horizontal = math.hypot(tx - mx, ty - my)
            for slot, weapon in enumerate(me["weapons"]):
                if not weapon:
                    continue
                kind = weapon["kind"]
                stats = weapon["stats"]
                if kind == "gun" and horizontal < stats.get("range", 230):
                    if weapon["ammo"] > 0 and weapon["reload"] == 0:
                        fire[slot] = True
                elif kind == "mortar" and 18 < horizontal < stats.get("range", 235):
                    fire[slot] = True

        act["aim"] = aim
        act["fire"] = fire
        act["reload"] = False
        mf.draw.point([goal_x, goal_y, mz], "#40c0ff", 5)
        mf.draw.label(
            "t100 loot · hp %.0f · cube %.0f · zone %.0f"
            % (me["hp"], me["cubes"], outside_distance)
        )
        return act


mf.run(Bot)
