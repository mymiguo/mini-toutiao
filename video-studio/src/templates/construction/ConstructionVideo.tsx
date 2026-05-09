import React from "react";
import { Sequence } from "remotion";
import { Background } from "../../common/Background";
import { StageCard } from "./StageCard";
import { ProgressBar } from "./ProgressBar";
import { COLORS } from "../../common/styles";

interface Scene {
  id: string;
  title: string;
  description: string;
  steps: string[];
  duration: number;
}

interface ConstructionVideoProps {
  title: string;
  scenes: Scene[];
}

export const ConstructionVideo: React.FC<ConstructionVideoProps> = ({ title, scenes }) => {
  return (
    <Background>
      {/* Title overlay — always visible */}
      <div
        style={{
          position: "absolute",
          top: 24,
          left: 120,
          fontSize: 24,
          color: COLORS.textDim,
          fontWeight: 400,
        }}
      >
        {title}
      </div>

      {scenes.map((scene, i) => {
        const startFrame = scenes.slice(0, i).reduce((acc, s) => acc + s.duration, 0) * 30;
        const durationFrames = scene.duration * 30;

        return (
          <Sequence key={scene.id} from={startFrame} durationInFrames={durationFrames}>
            <StageCard
              title={scene.title}
              description={scene.description}
              steps={scene.steps}
              startFrame={startFrame}
            />
            <ProgressBar current={i + 1} total={scenes.length} />
          </Sequence>
        );
      })}
    </Background>
  );
};
