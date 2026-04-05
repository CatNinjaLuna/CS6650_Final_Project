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
}