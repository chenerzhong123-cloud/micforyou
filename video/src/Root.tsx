import React from 'react';
import {Composition} from 'remotion';
import {Promo} from './Promo';
import production from '../production.json';

export const Root: React.FC = () => (
  <Composition id="MicForYouPromo" component={Promo} width={1920} height={1080}
    fps={production.fps} durationInFrames={production.durationSeconds * production.fps} />
);
