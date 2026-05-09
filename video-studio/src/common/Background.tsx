import React from "react";
import { AbsoluteFill } from "remotion";
import { COLORS } from "./styles";

export const Background: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        fontFamily: '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif',
        color: COLORS.text,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};
