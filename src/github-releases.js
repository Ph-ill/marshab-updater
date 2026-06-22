const OWNER = 'Ph-ill';
const REPO = 'marshab-updater';
const RELEASES_API = `/github-api/repos/${OWNER}/${REPO}/releases`;
const ASSET_NAME = 'firmware-release.json';

function cleanVersion(tagName){
  return String(tagName || '').replace(/^v/i, '');
}

function findFirmwareAsset(release){
  return (release.assets || []).find(asset => asset.name === ASSET_NAME) || null;
}

function rawFirmwareUrl(tagName){
  return `https://raw.githubusercontent.com/${OWNER}/${REPO}/main/firmware-assets/${tagName}/${ASSET_NAME}`;
}

export async function loadGithubReleaseIndex(){
  const response = await fetch(RELEASES_API, { cache:'no-store' });
  if(!response.ok) throw new Error(`GitHub releases returned ${response.status}`);
  const githubReleases = await response.json();
  const releases = githubReleases
    .filter(release => !release.draft)
    .map(release => ({ release, asset: findFirmwareAsset(release) }))
    .filter(item => item.asset)
    .map(({ release, asset }) => ({
      version: cleanVersion(release.tag_name),
      tag: release.tag_name,
      date: (release.published_at || release.created_at || '').slice(0, 10),
      label: release.name || release.tag_name,
      path: rawFirmwareUrl(release.tag_name),
      source: 'github-release',
      assetName: asset.name,
      prerelease: !!release.prerelease,
    }));
  const stable = releases.find(release => !release.prerelease) || releases[0];
  return {
    schema: 1,
    project: 'MarsHab',
    latest: stable?.version || null,
    releases,
  };
}
