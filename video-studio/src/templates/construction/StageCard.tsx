import React from "react";
import { spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS } from "../../common/styles";

interface StageCardProps {
  title: string;
  description: string;
  steps: string[];
  startFrame: number;
}

export const StageCard: React.FC<StageCardProps> = ({ title, description, steps, startFrame }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const localFrame = Math.max(0, frame - startFrame);

  const cardSpring = spring({
    frame: localFrame,
    fps,
    config: { damping: 20, stiffness: 120 },
  });

  const opacity = spring({
    frame: localFrame,
    fps,
    config: { damping: 50, stiffness: 200 },
  });

  return (
    <div
      style={{
        position: "absolute",
        top: 80,
        left: 120,
        right: 120,
        background: COLORS.bgCard,
        borderRadius: 16,
        padding: "48px 64px",
        transform: `scale(${0.9 + cardSpring * 0.1})`,
        opacity,
        border: `1px solid ${COLORS.accent2}`,
      }}
    >
      <h2 style={{ fontSize: 48, color: COLORS.accent, margin: "0 0 16px 0", fontWeight: 700 }}>
        {title}
      </h2>
      <p style={{ fontSize: 28, color: COLORS.textDim, margin: "0 0 40px 0", lineHeight: 1.6 }}>
        {description}
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        {steps.map((step, i) => {
          const stepDelay = 15 * i;
          const stepSpring = spring({
            frame: Math.max(0, localFrame - stepDelay),
            fps,
            config: { damping: 30, stiffness: 150 },
          });
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 24,
                opacity: stepSpring,
                transform: `translateX(${(1 - stepSpring) * 40}px)`,
              }}
            >
              <div
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: "50%",
                  background: COLORS.accent,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 22,
                  fontWeight: 700,
                  color: COLORS.white,
                  flexShrink: 0,
                }}
              >
                {i + 1}
              </div>
              <span style={{ fontSize: 32, color: COLORS.text }}>{step}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};
