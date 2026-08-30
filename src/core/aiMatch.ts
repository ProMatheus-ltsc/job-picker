/**
 * 单位匹配（05 §4.7 matchUnit 契约，Q-D4 双向包含匹配）
 */
/** jobUnit 与 aiUnit 双向包含匹配：相等 / jobUnit 含 aiUnit / aiUnit 含 jobUnit */
export function matchUnit(jobUnit: string, aiUnit: string): boolean {
  return jobUnit === aiUnit || jobUnit.includes(aiUnit) || aiUnit.includes(jobUnit);
}
