package worker3;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

@JsonIgnoreProperties(ignoreUnknown = true)
public class SimResponse {
  public String status;

  @JsonProperty("applied_joints")
  public Map<String, Double> appliedJoints;

  @JsonProperty("joint_count")
  public int jointCount;

  @JsonProperty("end_effector")
  public EndEffector endEffector;

  public boolean collision;

  public static class EndEffector {
    public double x;
    public double y;
    public double z;
  }
}