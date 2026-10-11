import { eventLabel } from "../lib/metrics";
import type { TrackingPlay } from "../lib/types";

interface TimelineProps {
  play: TrackingPlay;
  frameIndex: number;
  isPlaying: boolean;
  playbackRate: number;
  onFrameChange: (index: number) => void;
  onTogglePlayback: () => void;
  onRateChange: (rate: number) => void;
}

export function Timeline({
  play,
  frameIndex,
  isPlaying,
  playbackRate,
  onFrameChange,
  onTogglePlayback,
  onRateChange,
}: TimelineProps) {
  const progress = play.frames.length > 1 ? (frameIndex / (play.frames.length - 1)) * 100 : 0;
  const events = play.frames.flatMap((frame, index) => frame.event ? [{ index, event: frame.event }] : []);

  return (
    <div className="timeline-panel">
      <div className="transport">
        <button className="play-button" type="button" onClick={onTogglePlayback} aria-label={isPlaying ? "Pause" : "Play"}>
          {isPlaying ? "Ⅱ" : "▶"}
        </button>
        <button type="button" onClick={() => onFrameChange(Math.max(0, frameIndex - 1))} aria-label="Previous frame">−1</button>
        <button type="button" onClick={() => onFrameChange(Math.min(play.frames.length - 1, frameIndex + 1))} aria-label="Next frame">+1</button>
        <span className="frame-counter">
          <b>FRAME {String(play.frames[frameIndex].frameId).padStart(3, "0")}</b>
          <small>{(play.frames[frameIndex].timeMs / 1000).toFixed(1)} SEC</small>
        </span>
      </div>

      <div className="scrubber-wrap">
        <div className="film-track" aria-hidden="true">
          <span style={{ width: `${progress}%` }} />
          {events.map(({ index, event }) => (
            <i
              key={`${index}-${event}`}
              style={{ left: `${(index / Math.max(play.frames.length - 1, 1)) * 100}%` }}
              title={eventLabel(event)}
            />
          ))}
        </div>
        <input
          className="scrubber"
          type="range"
          min="0"
          max={play.frames.length - 1}
          value={frameIndex}
          onChange={(event) => onFrameChange(Number(event.target.value))}
          aria-label="Tracking frame"
        />
        <div className="event-labels">
          {events.map(({ index, event }) => (
            <button
              type="button"
              key={`${index}-${event}`}
              style={{ left: `${(index / Math.max(play.frames.length - 1, 1)) * 100}%` }}
              onClick={() => onFrameChange(index)}
            >
              {eventLabel(event)}
            </button>
          ))}
        </div>
      </div>

      <label className="rate-control">
        <span>PLAYBACK</span>
        <select value={playbackRate} onChange={(event) => onRateChange(Number(event.target.value))}>
          <option value={0.5}>0.5×</option>
          <option value={1}>1×</option>
          <option value={2}>2×</option>
        </select>
      </label>
    </div>
  );
}
