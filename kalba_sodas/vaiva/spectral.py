"""Spectral clustering of a distance matrix (numpy only).

* similarity: self-tuning Gaussian kernel (Zelnik-Manor & Perona 2004), σᵢ = distance to the 7th nearest form;
* normalised Laplacian L = I − D^-½ W D^-½, its smallest eigenvalues and eigenvectors;
* number of clusters: the largest gap between consecutive eigenvalues (eigengap), unless given;
* clusters: k-means (k-means++ start, many restarts) on the row-normalised eigenvectors (Ng, Jordan & Weiss 2002);
* layout: classical multidimensional scaling of the distances, so the drawing keeps the distances;
* quality: silhouette per form; agreement with other groupings: adjusted Rand index.
"""
from __future__ import annotations

from typing import Any

import numpy as np

KNN = 7
MAX_K = 12


def affinity(d: np.ndarray, knn: int = KNN) -> np.ndarray:
    n = len(d)
    k = min(knn, n - 1)
    sigma = np.sort(d, axis=1)[:, k]
    positive = d[d > 0]
    floor = max(1e-3, float(positive.min()) if positive.size else 1e-3)
    sigma = np.maximum(sigma, floor)
    w = np.exp(-(d ** 2) / np.outer(sigma, sigma))
    np.fill_diagonal(w, 0.0)
    return w


def laplacian_spectrum(w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    deg = w.sum(axis=1)
    inv = np.where(deg > 0, 1 / np.sqrt(np.where(deg > 0, deg, 1)), 0.0)
    lap = np.eye(len(w)) - inv[:, None] * w * inv[None, :]
    vals, vecs = np.linalg.eigh(lap)
    return np.clip(vals, 0, None), vecs


def eigengap_k(vals: np.ndarray, max_k: int = MAX_K) -> tuple[int, list[float]]:
    top = min(max_k, len(vals) - 1)
    gaps = [float(vals[k] - vals[k - 1]) for k in range(1, top + 1)]
    if top < 2:
        return 1, gaps
    k = max(range(2, top + 1), key=lambda k: gaps[k - 1])
    return k, gaps


def kmeans(x: np.ndarray, k: int, restarts: int = 25, iters: int = 100, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    best, best_cost = None, np.inf
    for _ in range(restarts):
        centers = [x[rng.integers(len(x))]]
        for _ in range(1, k):
            d2 = np.min(((x[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
            total = d2.sum()
            centers.append(x[rng.choice(len(x), p=d2 / total)] if total > 0 else x[rng.integers(len(x))])
        c = np.array(centers)
        for _ in range(iters):
            labels = ((x[:, None, :] - c[None]) ** 2).sum(-1).argmin(1)
            new = np.array([x[labels == j].mean(0) if np.any(labels == j) else c[j] for j in range(k)])
            if np.allclose(new, c):
                break
            c = new
        cost = ((x - c[labels]) ** 2).sum()
        if cost < best_cost - 1e-12:
            best, best_cost = labels, cost
    # number clusters by size, largest first
    order = sorted(range(k), key=lambda j: (-int(np.sum(best == j)), j))
    remap = {old: new for new, old in enumerate(order)}
    return np.array([remap[int(v)] for v in best])


def classical_mds(d: np.ndarray, dims: int = 2) -> np.ndarray:
    n = len(d)
    j = np.eye(n) - 1.0 / n
    b = -0.5 * j @ (d ** 2) @ j
    vals, vecs = np.linalg.eigh(b)
    idx = np.argsort(vals)[::-1][:dims]
    return vecs[:, idx] * np.sqrt(np.clip(vals[idx], 0, None))


def silhouette(d: np.ndarray, labels: np.ndarray) -> np.ndarray:
    n, out = len(d), np.zeros(len(d))
    clusters = np.unique(labels)
    if len(clusters) < 2:
        return out
    for i in range(n):
        same = (labels == labels[i])
        same[i] = False
        if not same.any():
            continue
        a = d[i, same].mean()
        b = min(d[i, labels == c].mean() for c in clusters if c != labels[i])
        out[i] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return out


def adjusted_rand(a: list[Any], b: list[Any]) -> float | None:
    if len(a) < 2:
        return None
    ai = {v: i for i, v in enumerate(sorted(set(a), key=str))}
    bi = {v: i for i, v in enumerate(sorted(set(b), key=str))}
    table = np.zeros((len(ai), len(bi)))
    for x, y in zip(a, b):
        table[ai[x], bi[y]] += 1
    comb = lambda v: v * (v - 1) / 2
    index = comb(table).sum()
    rows, cols, total = comb(table.sum(1)).sum(), comb(table.sum(0)).sum(), comb(len(a))
    expected = rows * cols / total if total else 0
    maximum = (rows + cols) / 2
    return float((index - expected) / (maximum - expected)) if maximum != expected else 1.0


def spectral_clusters(d: np.ndarray, k: int | None = None) -> dict[str, Any]:
    n = len(d)
    if n < 3:
        return {"labels": np.zeros(n, dtype=int), "k": 1, "k_auto": 1, "eigenvalues": [], "gaps": [], "vectors": np.zeros((n, n)),
                "embedding": np.zeros((n, 2)), "layout": classical_mds(d) if n else np.zeros((0, 2))}
    w = affinity(d)
    vals, vecs = laplacian_spectrum(w)
    k_auto, gaps = eigengap_k(vals)
    k = max(1, min(int(k or k_auto), n - 1, 30))
    return {"labels": labels_for(vecs, k), "k": k, "k_auto": k_auto, "eigenvalues": [float(v) for v in vals[:min(n, 16)]],
            "gaps": gaps, "vectors": vecs, "embedding": vecs[:, 1:3] if n > 2 else np.zeros((n, 2)), "layout": classical_mds(d)}


def labels_for(vecs: np.ndarray, k: int) -> np.ndarray:
    """k clusters from the first k eigenvectors, rows normalised to unit length."""
    if k < 2:
        return np.zeros(len(vecs), dtype=int)
    u = vecs[:, :k]
    norms = np.linalg.norm(u, axis=1, keepdims=True)
    return kmeans(u / np.where(norms > 0, norms, 1), k)


# -- helpers for graphs given as similarities, and for comparing two distance matrices ------------------------------

def affinity_clusters(w: np.ndarray, k: int | None = None) -> dict[str, Any]:
    """Spectral clusters of a graph given by its (symmetric, zero-diagonal) weights, e.g. lexical similarity."""
    vals, vecs = laplacian_spectrum(w)
    k_auto, gaps = eigengap_k(vals)
    k = max(1, min(int(k or k_auto), len(w) - 1, 30))
    return {"labels": labels_for(vecs, k), "k": k, "k_auto": k_auto, "eigenvalues": [float(v) for v in vals[:min(len(w), 16)]],
            "gaps": gaps, "vectors": vecs}


def signed_embedding(vecs: np.ndarray) -> np.ndarray:
    """Eigenvectors 2 and 3, with the arbitrary sign fixed (largest coordinate positive) so runs are reproducible."""
    coords = np.zeros((len(vecs), 2))
    take = min(2, max(0, vecs.shape[1] - 1))
    coords[:, :take] = vecs[:, 1:1 + take]
    for axis in range(take):
        if coords[np.argmax(np.abs(coords[:, axis])), axis] < 0:
            coords[:, axis] *= -1
    return coords


def rankdata(a: np.ndarray) -> np.ndarray:
    """Ranks 1 … n, ties get their average rank."""
    _, inv, counts = np.unique(a, return_inverse=True, return_counts=True)
    ends = np.cumsum(counts)
    return (ends - (counts - 1) / 2.0)[inv]


def spearman(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 3:
        return None
    rx, ry = rankdata(x), rankdata(y)
    sx, sy = rx.std(), ry.std()
    if sx == 0 or sy == 0:
        return None
    return float(((rx - rx.mean()) * (ry - ry.mean())).mean() / (sx * sy))


def mantel(a: np.ndarray, b: np.ndarray, permutations: int = 999, seed: int = 0) -> tuple[float | None, float | None]:
    """Spearman correlation of two distance matrices over pairs where both are known, and the one-sided
    permutation p-value (languages of ``b`` shuffled): how often chance alone gives as strong a correlation."""
    n = len(a)
    iu = np.triu_indices(n, 1)
    va, vb = a[iu], b[iu]
    ok = np.isfinite(va) & np.isfinite(vb)
    rho = spearman(va[ok], vb[ok])
    if rho is None or permutations <= 0:
        return rho, None
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(permutations):
        p = rng.permutation(n)
        vp = b[np.ix_(p, p)][iu]
        okp = np.isfinite(va) & np.isfinite(vp)
        r = spearman(va[okp], vp[okp])
        if r is not None and r >= rho:
            hits += 1
    return rho, (hits + 1) / (permutations + 1)


def upgma(d: np.ndarray) -> list[list[float]]:
    """Average-linkage tree: merges [a, b, height, size]; leaves are 0 … n-1, merge i makes node n + i."""
    n = len(d)
    dist = {(i, j): float(d[i, j]) for i in range(n) for j in range(i + 1, n)}
    size = {i: 1 for i in range(n)}
    active = set(range(n))
    merges, nxt = [], n
    while len(active) > 1:
        (a, b), h = min(dist.items(), key=lambda kv: (kv[1], kv[0]))
        active -= {a, b}
        for c in active:
            da = dist.pop((min(a, c), max(a, c)))
            db = dist.pop((min(b, c), max(b, c)))
            dist[(c, nxt)] = (da * size[a] + db * size[b]) / (size[a] + size[b])
        del dist[(a, b)]
        size[nxt] = size[a] + size[b]
        merges.append([a, b, h, size[nxt]])
        active.add(nxt)
        nxt += 1
    return merges
