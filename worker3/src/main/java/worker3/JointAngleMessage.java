package worker3;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public class JointAngleMessage {
  public String robotId;
  public String deviceId;
  public String serverId;
  public String clientId;
  public List<Double> jointAngles;  // 7 DOF for Franka Panda
  public String timestamp;          // ISO-8601
}