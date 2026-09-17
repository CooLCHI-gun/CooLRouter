import "./index.css";
import { Composition } from "remotion";
import { CooLRouterPromo } from "./CooLRouterPromo";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="CooLRouterPromo"
        component={CooLRouterPromo}
        durationInFrames={360}
        fps={30}
        width={1280}
        height={720}
      />
    </>
  );
};
