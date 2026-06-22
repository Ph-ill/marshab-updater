const CTRL_A = '\x01';
const CTRL_B = '\x02';
const CTRL_C = '\x03';
const CTRL_D = '\x04';

function delay(ms){
  return new Promise(resolve => setTimeout(resolve, ms));
}

export class MicroPythonSerial {
  constructor({ baudRate = 115200, onData = null, onDisconnect = null } = {}){
    this.baudRate = baudRate;
    this.onData = onData;
    this.onDisconnect = onDisconnect;
    this.port = null;
    this.reader = null;
    this.writer = null;
    this.decoder = new TextDecoder();
    this.encoder = new TextEncoder();
    this.buffer = '';
    this.waiters = [];
    this.reading = false;
    this.disconnectNotified = false;
  }

  get connected(){
    return !!this.port && !!this.reader && !!this.writer;
  }

  async connect(){
    if(!('serial' in navigator)) throw new Error('WebSerial is not available in this browser');
    this.port = await navigator.serial.requestPort();
    await this.port.open({ baudRate: this.baudRate });
    this.reader = this.port.readable.getReader();
    this.writer = this.port.writable.getWriter();
    this.reading = true;
    this.disconnectNotified = false;
    this.readLoop();
    return this;
  }

  async disconnect(){
    try{ await this.write(CTRL_B); }catch(_err){}
    this.reading = false;
    this.resolveWaiters(new Error('serial disconnected'));
    await this.releaseStreams();
    if(this.port){
      try{ await this.port.close(); }catch(_err){}
      this.port = null;
    }
  }

  async releaseStreams(){
    if(this.reader){
      try{ await this.reader.cancel(); }catch(_err){}
      try{ this.reader.releaseLock(); }catch(_err){}
      this.reader = null;
    }
    if(this.writer){
      try{ this.writer.releaseLock(); }catch(_err){}
      this.writer = null;
    }
  }

  async reopenExisting({ attempts = 8, delayMs = 900 } = {}){
    if(!this.port) throw new Error('serial port is not available for reconnect');
    this.reading = false;
    this.resolveWaiters(new Error('serial reconnecting'));
    await this.releaseStreams();
    let lastError = null;
    for(let i = 0; i < attempts; i++){
      try{
        if(!this.port.readable || !this.port.writable){
          try{ await this.port.open({ baudRate: this.baudRate }); }catch(err){
            if(!String(err.message || err).toLowerCase().includes('already open')) throw err;
          }
        }
        this.reader = this.port.readable.getReader();
        this.writer = this.port.writable.getWriter();
        this.clearBuffer();
        this.disconnectNotified = false;
        this.reading = true;
        this.readLoop();
        return this;
      }catch(err){
        lastError = err;
        await this.releaseStreams();
        await delay(delayMs);
      }
    }
    throw lastError || new Error('serial reconnect failed');
  }

  notifyDisconnect(reason = 'serial disconnected'){
    if(this.disconnectNotified) return;
    this.disconnectNotified = true;
    if(this.onDisconnect) this.onDisconnect(reason);
  }

  async readLoop(){
    while(this.reading && this.reader){
      try{
        const { value, done } = await this.reader.read();
        if(done){
          if(this.reading) this.notifyDisconnect('serial link closed');
          break;
        }
        if(value){
          const text = this.decoder.decode(value, { stream:true });
          this.buffer += text;
          if(this.onData) this.onData(text);
          this.checkWaiters();
        }
      }catch(err){
        if(this.reading){
          this.resolveWaiters(err);
          this.notifyDisconnect(err.message || 'serial link lost');
        }
        break;
      }
    }
  }

  async write(text){
    if(!this.writer) throw new Error('serial writer is not open');
    await this.writer.write(this.encoder.encode(text));
  }

  clearBuffer(){
    this.buffer = '';
  }

  waitFor(match, timeoutMs = 4000){
    return new Promise((resolve, reject) => {
      const waiter = { match, resolve, reject, timer:null };
      waiter.timer = setTimeout(() => {
        this.waiters = this.waiters.filter(w => w !== waiter);
        reject(new Error(`timeout waiting for ${String(match)}`));
      }, timeoutMs);
      this.waiters.push(waiter);
      this.checkWaiters();
    });
  }

  checkWaiters(){
    for(const waiter of [...this.waiters]){
      const matched = typeof waiter.match === 'string'
        ? this.buffer.includes(waiter.match)
        : waiter.match.test(this.buffer);
      if(matched){
        clearTimeout(waiter.timer);
        this.waiters = this.waiters.filter(w => w !== waiter);
        waiter.resolve(this.buffer);
      }
    }
  }

  resolveWaiters(err){
    for(const waiter of this.waiters){
      clearTimeout(waiter.timer);
      waiter.reject(err);
    }
    this.waiters = [];
  }

  async interrupt(){
    this.clearBuffer();
    await this.write(CTRL_C);
    await delay(80);
    await this.write(CTRL_C);
    await delay(120);
  }

  async enterRawRepl(){
    await this.interrupt();
    this.clearBuffer();
    await this.write(CTRL_A);
    await this.waitFor('raw REPL', 5000);
    await this.waitFor('>', 5000);
  }

  async exitRawRepl(){
    this.clearBuffer();
    await this.write(CTRL_B);
    await delay(100);
  }

  async exec(code, { timeoutMs = 8000 } = {}){
    if(!this.connected) throw new Error('serial port is not connected');
    const normalized = code.endsWith('\n') ? code : `${code}\n`;
    this.clearBuffer();
    await this.write(normalized + CTRL_D);
    const raw = await this.waitFor(/\x04[\s\S]*\x04/, timeoutMs);
    return parseRawExec(raw);
  }

  async softReset(){
    this.clearBuffer();
    await this.write(CTRL_D);
    await delay(1500);
  }

  async hardReset(){
    this.clearBuffer();
    try{
      await this.exec('import machine\nmachine.reset()', { timeoutMs: 1200 });
    }catch(_err){
      // machine.reset() tears down the VM/USB link before raw REPL can return.
    }
    await delay(2500);
  }
}

function parseRawExec(raw){
  const okIndex = raw.indexOf('OK');
  const body = okIndex >= 0 ? raw.slice(okIndex + 2) : raw;
  const first = body.indexOf(CTRL_D);
  if(first < 0) return { stdout: body, stderr: '', raw };
  const second = body.indexOf(CTRL_D, first + 1);
  const stdout = body.slice(0, first).replace(/^\r?\n/, '');
  const stderr = second >= 0 ? body.slice(first + 1, second) : body.slice(first + 1);
  if(stderr.trim()){
    const err = new Error(stderr.trim());
    err.stdout = stdout;
    err.stderr = stderr;
    err.raw = raw;
    throw err;
  }
  return { stdout, stderr, raw };
}
