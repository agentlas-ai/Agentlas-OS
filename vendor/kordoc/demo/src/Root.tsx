import { Composition } from "remotion"
import { KordocDemo } from "./KordocDemo"

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="KordocDemo"
      component={KordocDemo}
      durationInFrames={300}
      fps={30}
      width={1280}
      height={720}
    />
  )
}
