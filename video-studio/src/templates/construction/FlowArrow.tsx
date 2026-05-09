import React from "react";
import { spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS } from "../../common/styles";

interface FlowArrowProps {
  startFrame: number;
  direction: "down" | "right";
}

export const FlowArrow: React.FC<FlowArrowProps> = ({ startFrame, direction }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const localFrame = Math.max(0, frame - startFrame);

  const progress = spring({
    frame: localFrame,
    fps,
    config: { damping: 30, stiffness: 100 },
  });

  const isDown = direction === "down";

  return (
    <div
      style={{
        position: "absolute",
        ...(isDown
          ? { right: 160, top: "50%", width: 4, height: 80 }
          : { bottom: 60, left: "50%", height: 4, width: 80 }),
        background: COLORS.accent2,
        opacity: 0.5,
        transform: isDown ? `scaleY(${progress})` : `scaleX(${progress})`,
        transformOrigin: isDown ? "top" : "left",
      }}
    />
  );
};
