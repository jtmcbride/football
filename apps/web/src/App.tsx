import { useCallback, useEffect, useRef, useState } from "react";
import { FieldReplay } from "./components/FieldReplay";
import { PlaySidebar } from "./components/PlaySidebar";
import { Timeline } from "./components/Timeline";
import type { TrackingPlay } from "./lib/types";

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

  useEffect(() => {
    fetch("/plays/demo.json")
      .then((response) => {
        if (!response.ok) throw new Error(`Demo play returned HTTP ${response.status}`);
        return response.json() as Promise<TrackingPlay>;
      })
      .then(setPlay)
      .catch((error: unknown) => setLoadError(error instanceof Error ? error.message : "Could not load the demo play."));
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
            <h2>The viewer is ready for real tracking. The demo is not real NFL data.</h2>
          </div>
          <p>
            Big Data Bowl releases require a Kaggle account and acceptance of the competition rules, so raw tracking is not redistributed here. Use the included extractor to convert one downloaded play into this viewer’s compact JSON format.
          </p>
          <code>uv run football extract --tracking tracking_week_1.csv --plays plays.csv --players players.csv --game-id … --play-id … --output play.json</code>
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

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>{label}</span>
    </label>
  );
}
