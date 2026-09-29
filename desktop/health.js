export function healthBlockers(health) {
  const dependencies = Array.isArray(health?.dependencies) ? health.dependencies : [];
  return dependencies.filter((dependency) => {
    if (!dependency?.required || dependency.available) return false;
    return health?.status !== 'setup_needed' || !['kokoro', 'piper'].includes(dependency.name);
  });
}
