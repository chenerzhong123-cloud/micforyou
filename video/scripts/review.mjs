import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';
import path from 'node:path';
import {mkdir, readFile} from 'node:fs/promises';

const browserExecutable = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const production=JSON.parse(await readFile('production.json','utf8'));
const reviewDir=`out/review-${production.basename.split('-').at(-1)}`;
await mkdir(reviewDir, {recursive:true});
const serveUrl = await bundle({entryPoint:path.resolve('src/index.ts')});
const composition = await selectComposition({serveUrl, id:'MicForYouPromo', browserExecutable});
const requestedFrames=process.argv.slice(2).map(Number);
for (const frame of requestedFrames.length?requestedFrames:production.reviewFrames) {
  await renderStill({serveUrl, composition, browserExecutable, frame,
    output:`${reviewDir}/frame-${String(frame).padStart(4,'0')}.png`});
  console.log(`Rendered review frame ${frame} (${(frame/production.fps).toFixed(2)}s)`);
}
