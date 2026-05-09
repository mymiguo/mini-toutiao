import React from "react";
import { COLORS } from "../../common/styles";

interface ProgressBarProps {
  current: number;
  total: number;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({ current, total }) => {
  const pct = Math.round((current / total) * 100);
  return (
    <div
      style={{
        position: "absolute",
        bottom: 40,
        left: 120,
        right: 120,
        height: 6,
        background: COLORS.bgCard,
        borderRadius: 3,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          height: "100%",
          width: `${pct}%`,
          background: `linear-gradient(90deg, ${COLORS.accent}, ${COLORS.gold})`,
          borderRadius: 3,
          transition: "width 0.5s ease",
        }}
      />
      <span
        style={{
          position: "absolute",
          top: -32,
          right: 0,
          fontSize: 20,
          color: COLORS.textDim,
        }}
      >
        {current} / {total}
      </span>
    </div>
  );
};
