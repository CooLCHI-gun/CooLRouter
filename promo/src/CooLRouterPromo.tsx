import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
  Sequence,
  Interpolate,
  spring,
} from "remotion";

// ---------- palette ----------
const BG = "#020617";
const PANEL = "#0a0f22";
const CYAN = "#22d3ee";
const GREEN = "#34d399";
const AMBER = "#fbbf24";
const VIOLET = "#c084fc";
const PINK = "#f472b6";
const SLATE = "#94a3b8";
const DIM = "#64748b";
const WHITE = "#e2e8f0";

const MONO = "'JetBrains Mono', monospace";
const SERIF = "'Playfair Display', Georgia, serif";

// ---------- animated grid background ----------
const GridBG: React.FC<{opacity?: number}> = ({opacity = 0.6}) => {
  const frame = useCurrentFrame();
  const drift = frame * 0.4;
  const lines = [];
  for (let i = -4; i < 40; i++) {
    const x = ((i * 40 + drift) % (1280 + 120)) - 60;
    lines.push(
      <div
        key={`v${i}`}
        style={{
          position: "absolute",
          left: x,
          top: 0,
          width: 1,
          height: "100%",
          background: "rgba(30,41,59,0.5)",
        }}
      />
    );
    const y = ((i * 40 + drift * 0.6) % (720 + 120)) - 60;
    lines.push(
      <div
        key={`h${i}`}
        style={{
          position: "absolute",
          top: y,
          left: 0,
          height: 1,
          width: "100%",
          background: "rgba(30,41,59,0.4)",
        }}
      />
    );
  }
  return (
    <AbsoluteFill style={{opacity}}>
      <AbsoluteFill style={{background: BG}} />
      {lines}
    </AbsoluteFill>
  );
};

// ---------- glow orb ----------
const Orb: React.FC<{color: string; x: number; y: number; r: number; delay?: number}> = ({
  color,
  x,
  y,
  r,
  delay = 0,
}) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [delay, delay + 30], [0, 0.9], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const breathe = 1 + Math.sin(frame / 30) * 0.06;
  return (
    <div
      style={{
        position: "absolute",
        left: x - r * breathe,
        top: y - r * breathe,
        width: r * 2 * breathe,
        height: r * 2 * breathe,
        borderRadius: "50%",
        background: `radial-gradient(circle, ${color} 0%, transparent 70%)`,
        filter: "blur(2px)",
        opacity: o,
      }}
    />
  );
};

// ---------- Title reveal ----------
const Title: React.FC<{frame: number}> = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const op = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const scale = spring({
    frame,
    fps,
    config: {damping: 200, stiffness: 100},
  });
  return (
    <AbsoluteFill style={{justifyContent: "center", alignItems: "center", flexDirection: "column"}}>
      <div
        style={{
          color: CYAN,
          fontSize: 30,
          fontFamily: MONO,
          letterSpacing: 8,
          textTransform: "uppercase",
          opacity: op,
          transform: `translateY(${interpolate(frame, [0, 30], [30, 0])}px)`,
        }}
      >
        CooLRouter
      </div>
      <div
        style={{
          color: WHITE,
          fontSize: 58,
          fontFamily: SERIF,
          fontWeight: 700,
          marginTop: 12,
          textAlign: "center",
          opacity: op,
          scale: String(0.9 + scale * 0.1),
        }}
      >
        The Architecture of <br />
        Deliberate Delegation
      </div>
      <div
        style={{
          color: SLATE,
          fontSize: 20,
          fontFamily: MONO,
          marginTop: 20,
          maxWidth: 720,
          textAlign: "center",
          opacity: interpolate(frame, [15, 40], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
        }}
      >
        Where intuition is entrusted to a machine — and where it is not.
      </div>
      <div
        style={{
          color: DIM,
          fontSize: 14,
          fontFamily: MONO,
          marginTop: 28,
          opacity: interpolate(frame, [30, 55], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
        }}
      >
        intent-guided · 6 tiers · verify before you trust
      </div>
    </AbsoluteFill>
  );
};

// ---------- Tier ladder scene ----------
const TIER_DATA = [
  {name: "Tier 0 · Local", sub: "on-device · $0 · private", color: GREEN},
  {name: "Tier 1 · Cloud", sub: "frontier · metered", color: AMBER},
  {name: "Tier 2 · Research", sub: "RAG · citations", color: VIOLET},
  {name: "Tier 3 · Trend", sub: "real-time · web", color: PINK},
  {name: "Tier 4 · Agentic", sub: "autonomous · multi-step", color: CYAN},
  {name: "Tier 5 · Critique", sub: "self-eval · review", color: "#a78bfa"},
];

const TierLadder: React.FC = () => {
  const frame = useCurrentFrame();
  const start = 20;
  return (
    <AbsoluteFill style={{justifyContent: "center", alignItems: "center", flexDirection: "column"}}>
      <div
        style={{
          color: WHITE,
          fontSize: 36,
          fontFamily: SERIF,
          fontWeight: 700,
          marginBottom: 30,
          opacity: interpolate(frame, [start - 5, start + 10], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
        }}
      >
        Six faculties, one intent
      </div>
      <div style={{display: "flex", flexDirection: "column", gap: 12}}>
        {TIER_DATA.map((t, i) => {
          const f = start + i * 6;
          const appear = Math.min(1, Math.max(0, (frame - f) / 10));
          const x = interpolate(appear, [0, 1], [-80, 0]);
          const o = appear;
          return (
            <div
              key={t.name}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 18,
                minWidth: 520,
                opacity: o,
                transform: `translateX(${x}px)`,
              }}
            >
              <div style={{width: 14, height: 14, borderRadius: "50%", background: t.color, boxShadow: `0 0 16px ${t.color}`}} />
              <div style={{fontFamily: MONO, fontSize: 20, color: WHITE, width: 260}}>{t.name}</div>
              <div style={{fontFamily: MONO, fontSize: 15, color: SLATE}}>{t.sub}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ---------- Routing beam scene ----------
const RoutingBeam: React.FC = () => {
  const frame = useCurrentFrame();
  const start = 20;
  const progress = Math.min(1, (frame - start) / 90);
  const pct = progress * 100;
  const active = Math.floor(progress * 5);
  return (
    <AbsoluteFill style={{justifyContent: "center", alignItems: "center", flexDirection: "column"}}>
      <div
        style={{
          color: WHITE,
          fontSize: 34,
          fontFamily: SERIF,
          fontWeight: 700,
          marginBottom: 40,
          opacity: interpolate(frame, [start - 5, start + 8], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
        }}
      >
        A request finds its faculty
      </div>
      <div style={{position: "relative", width: 860, height: 120}}>
        {/* source */}
        <div style={{position: "absolute", left: 0, top: 50, width: 40, height: 20, background: WHITE, borderRadius: 6}}>
          <div style={{fontSize: 12, fontFamily: MONO, color: BG, textAlign: "center", lineHeight: 20}}>REQ</div>
        </div>
        {/* beam */}
        <div
          style={{
            position: "absolute",
            left: 44,
            top: 58,
            width: "100%",
            height: 4,
            background: "#22d3ee",
            transform: `scaleX(${progress})`,
            transformOrigin: "left",
          }}
        />
        {/* moving packet */}
        <div
          style={{
            position: "absolute",
            left: 44 + pct * (860 - 90),
            top: 52,
            width: 12,
            height: 12,
            borderRadius: "50%",
            background: "#22d3ee",
            boxShadow: "0 0 20px #22d3ee",
          }}
        />
        {/* tier nodes */}
        {TIER_DATA.map((t, i) => (
          <div
            key={t.name}
            style={{
              position: "absolute",
              left: 130 + i * 130,
              top: 20,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              opacity: active >= i ? 1 : 0.25,
            }}
          >
            <div style={{width: 12, height: 12, borderRadius: "50%", background: t.color, boxShadow: `0 0 14px ${t.color}`}} />
            <div style={{fontSize: 12, fontFamily: MONO, color: SLATE, marginTop: 8}}>{t.name.replace("Tier ", "T")}</div>
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ---------- Guardrail close ----------
const Guardrail: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const start = 20;
  const op = interpolate(frame, [start, start + 15], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const scale = spring({frame: frame - start, fps, config: {damping: 200, stiffness: 80}});
  return (
    <AbsoluteFill style={{justifyContent: "center", alignItems: "center", flexDirection: "column"}}>
      <div style={{fontFamily: MONO, fontSize: 16, color: CYAN, letterSpacing: 6, opacity: op}}>GUARDRAIL</div>
      <div
        style={{
          marginTop: 24,
          fontFamily: SERIF,
          fontSize: 40,
          fontWeight: 700,
          color: WHITE,
          textAlign: "center",
          maxWidth: 820,
          opacity: op,
          scale: String(scale),
        }}
      >
        Never trust a self-report.
      </div>
      <div
        style={{
          marginTop: 20,
          fontFamily: MONO,
          fontSize: 22,
          color: SLATE,
          textAlign: "center",
          opacity: interpolate(frame, [start + 15, start + 30], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
        }}
      >
        Corroborate from more than one vantage. <br /> Test against the running system.
      </div>
    </AbsoluteFill>
  );
};

// ---------- Flow orchestrator (parent) ----------
const Flow: React.FC = () => {
  return (
    <AbsoluteFill style={{background: "transparent"}}>
      <Sequence from={0} durationInFrames={70}>
        <GridBG />
        <Orb color={CYAN} x={950} y={150} r={160} />
        <Orb color={GREEN} x={220} y={560} r={140} delay={20} />
        <Title frame={0} />
      </Sequence>
      <Sequence from={70} durationInFrames={90}>
        <GridBG opacity={0.3} />
        <Orb color={VIOLET} x={300} y={160} r={150} />
        <TierLadder />
      </Sequence>
      <Sequence from={160} durationInFrames={110}>
        <GridBG opacity={0.3} />
        <Orb color={AMBER} x={1000} y={550} r={160} />
        <RoutingBeam />
      </Sequence>
      <Sequence from={270} durationInFrames={90}>
        <GridBG opacity={0.3} />
        <Orb color={GREEN} x={1000} y={180} r={170} />
        <Guardrail />
      </Sequence>
    </AbsoluteFill>
  );
};

export const CooLRouterPromo: React.FC = () => {
  return (
    <AbsoluteFill style={{background: BG}}>
      <Flow />
    </AbsoluteFill>
  );
};
