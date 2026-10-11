export interface PlayLink {
  gameId: string;
  playId: string;
  frameIndex: number;
}

const LINK_KEYS = ["game", "play", "frame"] as const;

export function parsePlayLink(search: string): PlayLink | null {
  const params = new URLSearchParams(search);
  const gameId = params.get("game");
  const playId = params.get("play");
  if (!gameId || !playId) return null;

  const frame = Number.parseInt(params.get("frame") ?? "0", 10);
  return { gameId, playId, frameIndex: Number.isFinite(frame) ? Math.max(0, frame) : 0 };
}

export function isLinkedTo(search: string, gameId: string, playId: string): boolean {
  const link = parsePlayLink(search);
  return link?.gameId === gameId && link.playId === playId;
}

export function withPlayLink(search: string, link: PlayLink): string {
  const params = new URLSearchParams(search);
  params.set("game", link.gameId);
  params.set("play", link.playId);
  params.set("frame", String(link.frameIndex));
  return `?${params.toString()}`;
}

export function withoutPlayLink(search: string): string {
  const params = new URLSearchParams(search);
  for (const key of LINK_KEYS) params.delete(key);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function clampFrame(frameIndex: number, frameCount: number): number {
  if (!Number.isFinite(frameIndex)) return 0;
  return Math.max(0, Math.min(frameIndex, frameCount - 1));
}
