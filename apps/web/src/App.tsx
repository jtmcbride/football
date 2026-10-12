import { useCallback, useEffect, useRef, useState } from "react";
import { FieldReplay } from "./components/FieldReplay";
import { PlayBrowser } from "./components/PlayBrowser";
import { PlaySidebar } from "./components/PlaySidebar";
import { Timeline } from "./components/Timeline";
import { fetchTrackingPlay } from "./lib/catalog";
import { clampFrame, isLinkedTo, parsePlayLink, withPlayLink, withoutPlayLink } from "./lib/playLink";
import { qualityBadge } from "./lib/provenance";
import type { TrackingPlay } from "./lib/types";

const INITIAL_PLAY_URLS = ["/plays/local-sample.json", "/plays/demo.json"] as const;

interface LocationPlay {
  play: TrackingPlay;
  frameIndex: number;
  linkError: string | null;
}

/** Resolves the play named by the current URL, falling back to the bundled sample. */
async function loadPlayForLocation(signal: AbortSignal): Promise<LocationPlay> {
  let lastError: Error | null = null;
  let linkError: string | null = null;
  const link = parsePlayLink(window.location.search);

  if (link) {
    try {
      const play = await fetchTrackingPlay(link.gameId, link.playId, signal);
      return { play, frameIndex: clampFrame(link.frameIndex, play.frames.length), linkError: null };
    } catch (error) {
      if (signal.aborted) throw error;
      const detail = error instanceof Error ? error.message : "unknown error";
      linkError = `Linked play ${link.gameId}/${link.playId} could not be loaded (${detail}). Showing the default play instead.`;
    }
  }

  for (const url of INITIAL_PLAY_URLS) {
    try {
      const response = await fetch(url, { signal });
      if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
      return { play: await response.json() as TrackingPlay, frameIndex: 0, linkError };
    } catch (error) {
      if (signal.aborted) throw error;
      lastError = error instanceof Error ? error : new Error(`Could not load ${url}`);
    }
  }
  throw lastError ?? new Error("No initial play is available.");
}

export default function App() {
  const [play, setPlay] = useState<TrackingPlay | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [showLabels, setShowLabels] = useState(true);
  const [showTrails, setShowTrails] = useState(true);
  const [showOrientation, setShowOrientation] = useState(false);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  // Restore the play named by the URL on first load and on browser back/forward.
  useEffect(() => {
    let controller = new AbortController();
    const restore = () => {
      controller.abort();
      controller = new AbortController();
      const { signal } = controller;
      loadPlayForLocation(signal)
        .then((next) => {
          if (signal.aborted) return;
          setPlay(next.play);
          setFrameIndex(next.frameIndex);
          setIsPlaying(false);
          setSelectedEntityId(null);
          setLoadError(next.linkError);
          if (next.linkError) replaceSearch(withoutPlayLink(window.location.search));
        })
        .catch((error: unknown) => {
          if (signal.aborted) return;
          setLoadError(error instanceof Error ? error.message : "Could not load an initial play.");
        });
    };
    restore();
    window.addEventListener("popstate", restore);
    return () => {
      controller.abort();
      window.removeEventListener("popstate", restore);
    };
  }, []);

  useEffect(() => {
    if (!isPlaying || !play) return;
    const timer = window.setInterval(() => {
      setFrameIndex((current) => {
        if (current >= play.frames.length - 1) {
          setIsPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, 100 / playbackRate);
    return () => window.clearInterval(timer);
  }, [isPlaying, play, playbackRate]);

  const changeFrame = useCallback((nextIndex: number) => {
    setFrameIndex(nextIndex);
  }, []);

  const selectCatalogPlay = useCallback((nextPlay: TrackingPlay) => {
    setPlay(nextPlay);
    setFrameIndex(0);
    setIsPlaying(false);
    setSelectedEntityId(null);
    setLoadError(null);
    // A new play is a history entry so Back returns to the previous one; re-selecting the same play is not.
    const { gameId, playId } = nextPlay.play;
    const search = withPlayLink(window.location.search, { gameId, playId, frameIndex: 0 });
    if (isLinkedTo(window.location.search, gameId, playId)) replaceSearch(search);
    else pushSearch(search);
  }, []);

  // Scrubbing rewrites the current entry only, and only while the URL still names the displayed play.
  useEffect(() => {
    if (!play || !isLinkedTo(window.location.search, play.play.gameId, play.play.playId)) return;
    replaceSearch(withPlayLink(window.location.search, {
      gameId: play.play.gameId,
      playId: play.play.playId,
      frameIndex,
    }));
  }, [frameIndex, play]);

  const loadFile = useCallback(async (file: File | undefined) => {
    if (!file) return;
    try {
      const candidate = JSON.parse(await file.text()) as TrackingPlay;
      if (candidate.schemaVersion !== 1 || !Array.isArray(candidate.frames) || candidate.frames.length === 0) {
        throw new Error("This is not a schemaVersion 1 tracking-play export.");
      }
      setPlay(candidate);
      setFrameIndex(0);
      setIsPlaying(false);
      setSelectedEntityId(null);
      setLoadError(null);
      replaceSearch(withoutPlayLink(window.location.search));
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not read that play export.");
    }
  }, []);

  if (!play) {
    return <main className="loading-state">{loadError ?? "Loading motion lab…"}</main>;
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Football Motion Lab home">
          <span className="brand-ball">◖</span>
          <span>FOOTBALL</span>
          <b>/ MOTION LAB</b>
        </a>
        <div className="source-pill">
          <i className={play.source.kind === "generated-demo" ? "demo" : "public"} />
          {play.source.name}
        </div>
        <nav aria-label="Primary">
          <a href="#play-browser">Plays</a>
          <a className="active" href="#replay">Replay</a>
          <a href="#data-notes">Data notes</a>
        </nav>
        <button className="open-button" type="button" onClick={() => fileInput.current?.click()}>
          Open play JSON
        </button>
        <input
          ref={fileInput}
          type="file"
          accept="application/json,.json"
          hidden
          onChange={(event) => void loadFile(event.target.files?.[0])}
        />
      </header>

      <main id="top">
        <section className="intro">
          <div>
            <p className="eyebrow">ALL-22 · FRAME-BY-FRAME</p>
            <h1>See the play<br />before the result.</h1>
          </div>
          <div className="intro-copy">
            <p>Inspect spacing, speed, orientation, and assignments from public tracking releases—one tenth of a second at a time.</p>
            <div className="legend">
              <span><i className="offense" /> {play.play.offense ?? "Offense"}</span>
              <span><i className="defense" /> {play.play.defense ?? "Defense"}</span>
              <span><i className="football" /> Ball</span>
            </div>
          </div>
        </section>

        {loadError ? <div className="error-banner" role="alert">{loadError}</div> : null}

        <PlayBrowser
          currentGameId={play.play.gameId}
          currentPlayId={play.play.playId}
          onSelectPlay={selectCatalogPlay}
        />

        <section className="replay-layout" id="replay">
          <div className="replay-main">
            <div className="replay-toolbar">
              <div>
                <p className="eyebrow">CURRENT PLAY</p>
                <h2>{play.play.title}</h2>
              </div>
              <div className="view-toggles" aria-label="Field overlays">
                <Toggle label="Labels" checked={showLabels} onChange={setShowLabels} />
                <Toggle label="Trails" checked={showTrails} onChange={setShowTrails} />
                <Toggle label="Facing" checked={showOrientation} onChange={setShowOrientation} />
              </div>
            </div>
            <FieldReplay
              play={play}
              frameIndex={frameIndex}
              showLabels={showLabels}
              showTrails={showTrails}
              showOrientation={showOrientation}
              onSelectEntity={setSelectedEntityId}
              selectedEntityId={selectedEntityId}
            />
            <Timeline
              play={play}
              frameIndex={frameIndex}
              isPlaying={isPlaying}
              playbackRate={playbackRate}
              onFrameChange={changeFrame}
              onTogglePlayback={() => {
                if (frameIndex >= play.frames.length - 1) setFrameIndex(0);
                setIsPlaying((current) => !current);
              }}
              onRateChange={setPlaybackRate}
            />
          </div>
          <PlaySidebar play={play} frameIndex={frameIndex} selectedEntityId={selectedEntityId} />
        </section>

        <section className="data-notes" id="data-notes">
          <div>
            <p className="eyebrow">DATA BOUNDARY</p>
            <h2>{dataBoundaryHeadline(play)}</h2>
          </div>
          {play.source.kind === "generated-demo" ? (
            <p>Run <code>make sample</code> after downloading the official sample to load a real tracked play. Larger Big Data Bowl releases require acceptance of their competition rules.</p>
          ) : (
            <p>
              Source: {play.source.trackingFile}. {play.source.missingFields?.length ? `Unavailable in this release: ${play.source.missingFields.join(", ")}.` : "All core motion fields are available."}
            </p>
          )}
          <code>make sample</code>
        </section>
      </main>
      <footer>
        <span>10 HZ TRACKING</span>
        <span>NORMALIZED LEFT → RIGHT</span>
        <span>SCHEMA V{play.schemaVersion}</span>
      </footer>
    </div>
  );
}

function dataBoundaryHeadline(play: TrackingPlay): string {
  if (play.source.kind === "generated-demo") return "The viewer is ready for real tracking. The demo is not real NFL data.";
  const status = qualityBadge(play);
  if (status === "invalid") return "This is real NFL tracking data that failed validation. Treat it as unreliable.";
  if (status === "incomplete") return "This replay uses real public NFL tracking data with gaps. See the provenance panel.";
  return "This replay uses real public NFL tracking data.";
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

function replaceSearch(search: string): void {
  window.history.replaceState(null, "", `${window.location.pathname}${search}${window.location.hash}`);
}

function pushSearch(search: string): void {
  window.history.pushState(null, "", `${window.location.pathname}${search}${window.location.hash}`);
}
