"""t8world: the map model for t800 (standard library only).

A Python port of the map/navigation part of rogue_agi's pilot (github.com/BrozJosef/mech-royale-rogue-agi,
mech/world.go, MIT; itself from giddygiddyboy, MIT). See t800/LICENSE and t800/LICENSE-giddygiddyboy.

- a 1 m raster of the terrain and building stacks (top, walk surface, overhanging slabs)
- straight-line shot clearance on that raster
- a 2 m navigation grid: blocked cells, surface height, wall clearance, connected components
- A* paths, breadth-first searches with a stamp buffer, map exposure

Building the grids takes a few seconds in Python, so `python t8world.py ARENA_DIR CACHE` precomputes
them at image build time. At runtime the cache is used only if its hash matches the mounted map.
"""
import hashlib
import heapq
import json
import math
import os
import pickle
import sys
import time
from array import array

STEP_UP = 1.2
NAV_RADIUS = 2.6
NBRS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
CACHE_VERSION = 3


def map_hash(mdir):
    h = hashlib.sha1()
    for f in ("v2/world.json", "v2/terrain.i16"):
        with open(os.path.join(mdir, f), "rb") as fh:
            h.update(fh.read())
    h.update(str(CACHE_VERSION).encode())
    return h.hexdigest()


class World:
    def __init__(self, mdir, cache=None):
        self.ok = False
        t0 = time.perf_counter()
        hsh = map_hash(mdir)
        if cache and os.path.isfile(cache):
            try:
                with open(cache, "rb") as fh:
                    data = pickle.load(fh)
                if data.get("hash") == hsh:
                    self.__dict__.update(data["state"])
                    self._runtime_init()
                    self.ok = True
                    self.load_s = time.perf_counter() - t0
                    self.cached = True
                    return
            except Exception:
                pass
        self._build(mdir)
        self.hash = hsh
        self._runtime_init()
        self.ok = True
        self.cached = False
        self.load_s = time.perf_counter() - t0

    def save(self, path):
        skip = {"g", "came", "stamp", "closed", "gen", "expo", "main_near", "ok", "load_s", "cached"}
        state = {k: v for k, v in self.__dict__.items() if k not in skip}
        with open(path, "wb") as fh:
            pickle.dump({"hash": self.hash, "state": state}, fh, protocol=pickle.HIGHEST_PROTOCOL)

    def _runtime_init(self):
        n = self.NNX * self.NNY
        self.g = array("f", bytes(4 * n))
        self.came = array("i", bytes(4 * n))
        self.stamp = array("I", bytes(4 * n))
        self.closed = array("I", bytes(4 * n))
        self.gen = 0
        self.expo = {}
        self.main_near = None

    # ------------------------------------------------------------------ build
    def _build(self, mdir):
        with open(os.path.join(mdir, "v2", "world.json"), "r", encoding="utf-8") as fh:
            wj = json.load(fh)
        ter = wj["terrain"]
        self.MinX, self.MinY = float(ter["minX"]), float(ter["minY"])
        self.NX, self.NY = int(ter["nx"]), int(ter["ny"])
        scale = float(ter.get("scale", 0.01))
        b = wj["bounds"]
        self.BX0, self.BX1, self.BY0, self.BY1 = b["minX"], b["maxX"], b["minY"], b["maxY"]
        raw = array("h")
        with open(os.path.join(mdir, "v2", "terrain.i16"), "rb") as fh:
            raw.frombytes(fh.read())
        if sys.byteorder == "big":
            raw.byteswap()
        n = self.NX * self.NY
        ground = array("f", [v * scale for v in raw[:n]])
        self.Ground = ground

        NX, MinX, MinY, NY = self.NX, self.MinX, self.MinY, self.NY
        cells = {}
        for p in wj["prisms"]:
            rings = [p["ring"]] + list(p.get("holes") or [])
            ys = p["ring"][1::2]
            j0 = max(int(math.ceil(min(ys) - MinY)), 0)
            j1 = min(int(math.floor(max(ys) - MinY)), NY - 1)
            iv = (float(p["base"]), float(p["top"]), p.get("kind") == "bridge")
            edges = []
            for r in rings:
                m = len(r) // 2
                for a in range(m):
                    c = (a + 1) % m
                    edges.append((r[a * 2], r[a * 2 + 1], r[c * 2], r[c * 2 + 1]))
            for j in range(j0, j1 + 1):
                y = MinY + j + 1e-4
                xs = []
                for x0, y0, x1, y1 in edges:
                    if (y0 <= y) != (y1 <= y):
                        xs.append(x0 + (y - y0) / (y1 - y0) * (x1 - x0))
                xs.sort()
                row = j * NX
                for k in range(0, len(xs) - 1, 2):
                    i0 = max(int(math.ceil(xs[k] - MinX)), 0)
                    i1 = min(int(math.floor(xs[k + 1] - MinX)), NX - 1)
                    for i in range(i0, i1 + 1):
                        cells.setdefault(row + i, []).append(iv)
        top = array("f", ground)
        walk = array("f", ground)
        slabs = {}
        for idx, ivs in cells.items():
            ivs.sort(key=lambda v: v[0])
            g = ground[idx]
            t = g
            deck = -1e9
            for base, tp, bridge in ivs:
                if tp <= t:
                    continue
                if base <= t + 1.5:
                    t = tp
                    continue
                slabs.setdefault(idx, []).append((base, tp))
                if base - t < 10.5 and bridge and tp - g < 6.5:
                    deck = tp
            top[idx] = t
            walk[idx] = deck if deck > t else t
        self.Top, self.Walk, self.Slabs = top, walk, slabs
        self._build_nav()

    def _build_nav(self):
        NS = 2.0
        self.NS = NS
        NNX = (self.NX + 1) // 2
        NNY = (self.NY + 1) // 2
        self.NNX, self.NNY = NNX, NNY
        n = NNX * NNY
        NX, NY = self.NX, self.NY
        top, ground, walk, slabs = self.Top, self.Ground, self.Walk, self.Slabs
        # prism tops (or -inf where there is only terrain), for the wall test
        ptop = array("f", [-1e9]) * (NX * NY)
        for idx in range(NX * NY):
            if top[idx] - ground[idx] > 0.05:
                ptop[idx] = top[idx]
        offs = [(di, dj) for dj in range(-2, 3) for di in range(-2, 3) if di * di + dj * dj <= NAV_RADIUS * NAV_RADIUS]
        blocked = bytearray(n)
        surf = array("f", bytes(4 * n))
        bx0, bx1, by0, by1 = self.BX0 + NAV_RADIUS, self.BX1 - NAV_RADIUS, self.BY0 + NAV_RADIUS, self.BY1 - NAV_RADIUS
        # raster cells near any prism: only nav cells close to one need the full wall test
        near = bytearray(n)
        for idx in range(NX * NY):
            if ptop[idx] > -1e8 or idx in slabs:
                j, i = divmod(idx, NX)
                ci, cj = i // 2, j // 2
                for dj in (-2, -1, 0, 1, 2):
                    for di in (-2, -1, 0, 1, 2):
                        a, bb = ci + di, cj + dj
                        if 0 <= a < NNX and 0 <= bb < NNY:
                            near[bb * NNX + a] = 1
        for c in range(n):
            ci, cj = c % NNX, c // NNX
            i, j = min(ci * 2, NX - 1), min(cj * 2, NY - 1)
            x, y = self.MinX + ci * NS, self.MinY + cj * NS
            idx = j * NX + i
            z = walk[idx]
            surf[c] = z
            if not (bx0 < x < bx1 and by0 < y < by1):
                blocked[c] = 1
                continue
            if not near[c]:
                continue
            if walk[idx] <= top[idx] and top[idx] - ground[idx] > 1.5:
                blocked[c] = 1  # a roof
                continue
            lo, hi = z + STEP_UP, z + 9
            for di, dj in offs:
                a, bb = i + di, j + dj
                if a < 0 or bb < 0 or a >= NX or bb >= NY:
                    continue
                k = bb * NX + a
                if ptop[k] > lo and ground[k] < hi:
                    blocked[c] = 1
                    break
                sl = slabs.get(k)
                if sl:
                    hit = False
                    for sb, st in sl:
                        if st > lo and sb < hi:
                            hit = True
                            break
                    if hit:
                        blocked[c] = 1
                        break
        self.Blocked, self.Surf = blocked, surf

        clear = array("f", [1e9]) * n
        q = []
        for c in range(n):
            if blocked[c]:
                clear[c] = 0
                q.append(c)
        h = 0
        while h < len(q):
            c = q[h]
            h += 1
            d = clear[c] + NS
            if d > 20:
                continue
            ci, cj = c % NNX, c // NNX
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                i, j = ci + di, cj + dj
                if 0 <= i < NNX and 0 <= j < NNY:
                    nb = j * NNX + i
                    if clear[nb] > d:
                        clear[nb] = d
                        q.append(nb)
        for c in range(n):
            if clear[c] > 20:
                clear[c] = 20
        self.Clearance = clear

        comp = array("i", bytes(4 * n))
        label, best_n, best_size = 0, 0, 0
        for c0 in range(n):
            if blocked[c0] or comp[c0]:
                continue
            label += 1
            comp[c0] = label
            q = [c0]
            h = 0
            while h < len(q):
                c = q[h]
                h += 1
                ci, cj = c % NNX, c // NNX
                sc = surf[c]
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    i, j = ci + di, cj + dj
                    if 0 <= i < NNX and 0 <= j < NNY:
                        nb = j * NNX + i
                        if comp[nb] == 0 and not blocked[nb] and abs(surf[nb] - sc) <= 2.2:
                            comp[nb] = label
                            q.append(nb)
            if len(q) > best_size:
                best_size, best_n = len(q), label
        self.Comp, self.MainComp = comp, best_n

    # ------------------------------------------------------------------ queries
    def vidx(self, x, y):
        i = int(round(x - self.MinX))
        j = int(round(y - self.MinY))
        i = 0 if i < 0 else (self.NX - 1 if i >= self.NX else i)
        j = 0 if j < 0 else (self.NY - 1 if j >= self.NY else j)
        return j * self.NX + i

    def in_bounds(self, x, y):
        return self.BX0 < x < self.BX1 and self.BY0 < y < self.BY1

    def ground_at(self, x, y):
        fx = min(max(x - self.MinX, 0.0), self.NX - 1 - 1e-6)
        fy = min(max(y - self.MinY, 0.0), self.NY - 1 - 1e-6)
        i, j = int(fx), int(fy)
        tx, ty = fx - i, fy - j
        G, NX = self.Ground, self.NX
        k = j * NX + i
        return (G[k] * (1 - tx) + G[k + 1] * tx) * (1 - ty) + (G[k + NX] * (1 - tx) + G[k + NX + 1] * tx) * ty

    def walk_at(self, x, y):
        return self.Walk[self.vidx(x, y)]

    def top_at(self, x, y):
        return self.Top[self.vidx(x, y)]

    def obst(self, x, y):
        k = self.vidx(x, y)
        return self.Top[k] - self.Ground[k] > 1.2

    def solid(self, x, y, z):
        k = self.vidx(x, y)
        if z < self.Top[k] - 0.05:
            return True
        sl = self.Slabs.get(k)
        if sl:
            for b, t in sl:
                if b < z < t:
                    return True
        return False

    def clear(self, a, b, step=1.0):
        """Shot clearance on the raster (terrain and buildings; trees never stop shots)."""
        ax, ay, az = a[0], a[1], a[2]
        dx, dy, dz = b[0] - ax, b[1] - ay, b[2] - az
        d = math.sqrt(dx * dx + dy * dy + dz * dz)
        n = int(d / step) + 1
        inv = 1.0 / n
        top, slabs, NX, NY, MinX, MinY = self.Top, self.Slabs, self.NX, self.NY, self.MinX, self.MinY
        sx, sy, sz = dx * inv, dy * inv, dz * inv
        x, y, z = ax - MinX + 0.5, ay - MinY + 0.5, az
        for _ in range(1, n):
            x += sx
            y += sy
            z += sz
            i, j = int(x), int(y)
            if i < 0 or j < 0 or i >= NX or j >= NY:
                continue
            k = j * NX + i
            if z < top[k] - 0.05:
                return False
            if k in slabs:
                for sb, st in slabs[k]:
                    if sb < z < st:
                        return False
        return True

    # nav grid
    def cell(self, x, y):
        ci = int(round((x - self.MinX) / self.NS))
        cj = int(round((y - self.MinY) / self.NS))
        ci = 0 if ci < 0 else (self.NNX - 1 if ci >= self.NNX else ci)
        cj = 0 if cj < 0 else (self.NNY - 1 if cj >= self.NNY else cj)
        return cj * self.NNX + ci

    def cell_pos(self, c):
        return self.MinX + (c % self.NNX) * self.NS, self.MinY + (c // self.NNX) * self.NS

    def free(self, x, y):
        return not self.Blocked[self.cell(x, y)]

    def nearest_free(self, c):
        B = self.Blocked
        if not B[c]:
            return c
        NNX, NNY = self.NNX, self.NNY
        ci, cj = c % NNX, c // NNX
        for r in range(1, 21):
            best, bd = -1, 1 << 30
            for dj in range(-r, r + 1):
                j = cj + dj
                if j < 0 or j >= NNY:
                    continue
                step = 1 if abs(dj) == r else 2 * r
                for di in range(-r, r + 1, step):
                    i = ci + di
                    if 0 <= i < NNX and not B[j * NNX + i]:
                        d = di * di + dj * dj
                        if d < bd:
                            best, bd = j * NNX + i, d
            if best >= 0:
                return best
        return -1

    def can_step(self, a, b, diag):
        if self.Blocked[b]:
            return False
        return self.Surf[b] - self.Surf[a] <= (3.1 if diag else 2.2)

    def path(self, sx, sy, gx, gy, max_expand=6000, budget_s=0.012):
        s = self.nearest_free(self.cell(sx, sy))
        g = self.nearest_free(self.cell(gx, gy))
        if s < 0 or g < 0:
            return None, False
        if s == g:
            return [s], True
        self.gen += 1
        gen = self.gen
        NNX, NNY, NS = self.NNX, self.NNY, self.NS
        B, S, CL = self.Blocked, self.Surf, self.Clearance
        G, came, stamp, closed = self.g, self.came, self.stamp, self.closed
        gi, gj = g % NNX, g // NNX

        def hfun(c):
            dx = abs(c % NNX - gi)
            dy = abs(c // NNX - gj)
            return ((dx if dx > dy else dy) + 0.4142 * (dy if dx > dy else dx)) * NS * 1.15

        G[s] = 0
        came[s] = -1
        stamp[s] = gen
        heap = [(hfun(s), s)]
        best, best_h = s, hfun(s)
        found = False
        end = time.perf_counter() + budget_s
        n = 0
        while heap and n < max_expand:
            n += 1
            if (n & 255) == 0 and time.perf_counter() > end:
                break
            _, c = heapq.heappop(heap)
            if closed[c] == gen:
                continue
            closed[c] = gen
            if c == g:
                found = True
                best = c
                break
            hc = hfun(c)
            if hc < best_h:
                best, best_h = c, hc
            ci, cj = c % NNX, c // NNX
            sc, gc = S[c], G[c]
            for k in range(8):
                di, dj = NBRS[k]
                i, j = ci + di, cj + dj
                if i < 0 or j < 0 or i >= NNX or j >= NNY:
                    continue
                nb = j * NNX + i
                if closed[nb] == gen or B[nb]:
                    continue
                diag = k >= 4
                if S[nb] - sc > (3.1 if diag else 2.2):
                    continue
                step = NS
                if diag:
                    if B[cj * NNX + i] or B[j * NNX + ci]:
                        continue
                    step *= 1.4142
                cl = CL[nb]
                if cl < 4:
                    step *= 1 + (4 - cl) * 0.15
                ng = gc + step
                if stamp[nb] != gen or ng < G[nb]:
                    G[nb] = ng
                    came[nb] = c
                    stamp[nb] = gen
                    heapq.heappush(heap, (ng + hfun(nb), nb))
        out = []
        c = best
        while c >= 0:
            out.append(c)
            if c == s:
                break
            c = came[c]
        out.reverse()
        return out, found

    def bfs(self, start, visit, max_steps=1e9, max_nodes=1e9):
        """Breadth-first over the nav grid from cell start. visit(c, steps) returns False to stop."""
        NNX, NNY = self.NNX, self.NNY
        B, S, G, stamp = self.Blocked, self.Surf, self.g, self.stamp
        self.gen += 1
        gen = self.gen
        q = [start]
        stamp[start] = gen
        G[start] = 0
        h = 0
        while h < len(q) and h < max_nodes:
            c = q[h]
            h += 1
            steps = G[c]
            if steps > max_steps:
                break
            if visit(c, steps) is False:
                break
            ci, cj = c % NNX, c // NNX
            sc = S[c]
            for k in range(8):
                di, dj = NBRS[k]
                i, j = ci + di, cj + dj
                if i < 0 or j < 0 or i >= NNX or j >= NNY:
                    continue
                nb = j * NNX + i
                if stamp[nb] == gen or B[nb]:
                    continue
                if S[nb] - sc > (3.1 if k >= 4 else 2.2):
                    continue
                if k >= 4 and (B[cj * NNX + i] or B[j * NNX + ci]):
                    continue
                stamp[nb] = gen
                G[nb] = steps + 1
                q.append(nb)

    def line_walkable(self, x0, y0, x1, y1):
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        n = int(d) + 1
        prev = self.cell(x0, y0)
        B, S = self.Blocked, self.Surf
        for k in range(1, n + 1):
            t = k / n
            c = self.cell(x0 + dx * t, y0 + dy * t)
            if c == prev:
                continue
            if B[c] or S[c] - S[prev] > 3.1:
                return False
            prev = c
        return True

    def reachable(self, x, y):
        c = self.cell(x, y)
        return not self.Blocked[c] and self.Comp[c] == self.MainComp

    def off_main(self, x, y):
        c = self.nearest_free(self.cell(x, y))
        return c < 0 or self.Comp[c] != self.MainComp

    def main_near_of(self, c):
        if self.main_near is None:
            NNX, NNY = self.NNX, self.NNY
            n = NNX * NNY
            near = array("i", [-1]) * n
            depth = bytearray(n)
            q = []
            for i in range(n):
                if not self.Blocked[i] and self.Comp[i] == self.MainComp:
                    near[i] = i
                    q.append(i)
            h = 0
            while h < len(q):
                c0 = q[h]
                h += 1
                if depth[c0] >= 20:
                    continue
                ci, cj = c0 % NNX, c0 // NNX
                for di, dj in NBRS:
                    i, j = ci + di, cj + dj
                    if 0 <= i < NNX and 0 <= j < NNY:
                        nb = j * NNX + i
                        if near[nb] < 0:
                            near[nb] = near[c0]
                            depth[nb] = depth[c0] + 1
                            q.append(nb)
            self.main_near = near
        return self.main_near[c]

    def escape_plan(self, x, y):
        s = self.nearest_free(self.cell(x, y))
        if s < 0:
            return None
        best = [-1, 1e18]

        def visit(c, steps):
            m = self.main_near_of(c)
            if m >= 0:
                cx, cy = self.cell_pos(c)
                mx, my = self.cell_pos(m)
                sc = steps * self.NS + 4 * math.hypot(mx - cx, my - cy)
                if sc < best[1]:
                    best[0], best[1] = c, sc

        self.bfs(s, visit, max_nodes=20000)
        if best[0] < 0:
            return None
        lx, ly = self.cell_pos(best[0])
        mx, my = self.cell_pos(self.main_near_of(best[0]))
        d = math.hypot(mx - lx, my - ly)
        if d > 0.1:
            ex, ey = mx + (mx - lx) / d * 5, my + (my - ly) / d * 5
            if self.in_bounds(ex, ey) and self.reachable(ex, ey):
                mx, my = ex, ey
        return (lx, ly), (mx, my)

    def exposure(self, x, y):
        c = self.cell(x, y)
        v = self.expo.get(c)
        if v is not None:
            return v
        cx, cy = self.cell_pos(c)
        z = self.walk_at(cx, cy) + 7
        total = 0.0
        top, NX, NY, MinX, MinY = self.Top, self.NX, self.NY, self.MinX, self.MinY
        for k in range(24):
            a = k * math.pi / 12
            ca, sa = math.cos(a), math.sin(a)
            d = 2.5
            while d < 200:
                px, py = cx + ca * d, cy + sa * d
                if not (self.BX0 < px < self.BX1 and self.BY0 < py < self.BY1):
                    break
                i, j = int(round(px - MinX)), int(round(py - MinY))
                if 0 <= i < NX and 0 <= j < NY and z < top[j * NX + i] - 0.05:
                    break
                d += 2.5
            total += d
        v = total / (24 * 200)
        self.expo[c] = v
        return v


if __name__ == "__main__":
    # build-time cache: python t8world.py ARENA_DIR CACHE_PATH
    t0 = time.perf_counter()
    w = World(sys.argv[1])
    w.save(sys.argv[2])
    print("t8world: built %dx%d nav grid in %.1fs, main component %d" % (w.NNX, w.NNY, time.perf_counter() - t0, w.MainComp))
