package worker3;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public class JointAngleMessage {
  // old field kept for backward compatibility
  public String robotId;

  // new fields for registration-service lookup
  public String labId;
  public String deviceId;

  public List<Double> jointAngles;  // 7 DOF for Franka Panda
  public long timestamp;
}