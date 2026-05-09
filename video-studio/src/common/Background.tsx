import React from "react";
import { AbsoluteFill } from "remotion";
import { COLORS, FONT_FAMILY } from "./styles";

export const Background: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        fontFamily: FONT_FAMILY,
        color: COLORS.text,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};
