package worker3;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public class JointAngleMessage {
  public String robotId;
  public List<Double> jointAngles;  // 7 DOF for Franka Panda
  public long timestamp;
}