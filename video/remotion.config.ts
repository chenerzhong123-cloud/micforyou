import {Config} from '@remotion/cli/config';

Config.setEntryPoint('./src/index.ts');
Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(92);
Config.setOverwriteOutput(true);
Config.setConcurrency(6);
Config.setBrowserExecutable('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');
