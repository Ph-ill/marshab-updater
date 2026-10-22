// The Long Voyage release list is a static file in this repo (firmware/index.json, written by
// tools/build_release.py), served from the same origin: no GitHub API, no rate limit, no proxy.

export async function fetchJson(url){
  const response = await fetch(url, { cache: 'no-cache' });
  if(!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

export async function loadReleaseIndex(){
  const index = await fetchJson('./firmware/index.json');
  if(!Array.isArray(index.releases)) throw new Error('firmware/index.json has no releases list');
  return index;
}

export async function loadRuntimeSpec(){
  return fetchJson('./firmware/runtime.json');
}

// Semver-ish: 1.2.3 > 1.2.3-coex > 1.2.2. A leading "v" is ignored; missing parts count as 0.
export function compareVersions(a, b){
  const parse = v => {
    const [core, ...rest] = String(v || '').replace(/^v/i, '').split('-');
    const nums = core.split('.').map(n => Number.parseInt(n, 10) || 0);
    while(nums.length < 3) nums.push(0);
    return { nums, pre: rest.join('-') };
  };
  const x = parse(a), y = parse(b);
  for(let i = 0; i < 3; i++) if(x.nums[i] !== y.nums[i]) return x.nums[i] - y.nums[i];
  if(x.pre === y.pre) return 0;
  if(!x.pre) return 1;
  if(!y.pre) return -1;
  return x.pre < y.pre ? -1 : 1;
}
