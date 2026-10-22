import { compareVersions } from './releases.js';

// MicroPython itself (.uf2) cannot be written over Web Serial. The board has to be in BOOTSEL mode,
// where it shows up as a USB drive (RPI-RP2 / RP2350) and takes the .uf2 by drag and drop.
// The .uf2 files are linked from micropython.org; firmware/runtime.json carries their size and sha256.
export function runtimeStatus(runtimeSpec, info, releaseRuntimeMin){
  const need = releaseRuntimeMin || runtimeSpec?.version || null;
  const have = info?.runtime?.mpy || null;
  if(!need) return { state: 'none', need, have };
  if(!have) return { state: 'unknown', need, have };
  const cmp = compareVersions(have, need);
  return { state: cmp >= 0 ? (compareVersions(have, runtimeSpec?.version || need) === 0 ? 'ok' : 'newer') : 'old', need, have };
}

export function boardSupported(runtimeSpec, board){
  return !!(runtimeSpec?.boards && board && runtimeSpec.boards[board]);
}

// Shell commands to check a downloaded .uf2 against the published sha256.
export function verifyCommands(fileName){
  return {
    linux: `sha256sum ${fileName}`,
    mac: `shasum -a 256 ${fileName}`,
    windows: `certutil -hashfile ${fileName} SHA256`,
  };
}

// machine.bootloader() drops the board straight into BOOTSEL: no button press needed.
export async function rebootToBootsel(device){
  try{
    await device.exec('import machine\nmachine.bootloader()', { timeoutMs: 1500 });
  }catch(_err){
    // the USB serial link disappears as the ROM bootloader takes over; that is the success path
  }
  try{ await device.disconnect({ reset: false }); }catch(_err){}
}
