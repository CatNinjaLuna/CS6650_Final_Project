package aggregator;

import java.util.List;

/**
 * Represents the WebSocket payload sent to the frontend after each Isaac Sim job.
 *
 * Populated by worker3 and published to Redis as JSON. The aggregator deserializes
 * this from the Redis message and broadcasts it to all connected WebSocket clients.
 *
 * Example payload:
 * {
 *   "deviceId":    "arm-1",
 *   "module":      "kinematics",
 *   "jointAngles": [0.1, -0.3, 0.2, -1.5, 0.0, 1.8, 0.4],
 *   "endEffector": { "x": 0.41, "y": 0.28, "z": 0.35 },
 *   "collision":   false,
 *   "latency":     14
 * }
 */
public class SimResult {
  /** Robot identifier, e.g. "arm-1". Sourced from JointAngleMessage.robotId. */
  public String deviceId;

  /** Task module type. Currently always "kinematics". */
  public String module;

  /** Applied joint positions for Franka Panda (7 DOF), in radians. */
  public List<Double> jointAngles;

  /** End-effector world position after joint application. */
  public EndEffector endEffector;

  /** True if Isaac Sim detected a collision during this step. */
  public boolean collision;

  /** Round-trip time from SQS receive to Isaac Sim response, in milliseconds. */
  public long latency;

  public static class EndEffector {
    public double x;
    public double y;
    public double z;
  }
}