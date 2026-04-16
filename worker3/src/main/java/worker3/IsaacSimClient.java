package worker3;

import com.fasterxml.jackson.annotation.JsonProperty;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;

@Component
public class IsaacSimClient {

  private static final Logger log = LoggerFactory.getLogger(IsaacSimClient.class);
  private static final String UPDATE_PATH = "/roboparam/roboparam/update";

  private final RestTemplate restTemplate;
  private final String baseUrl;

  @Value("${worker.isaac-sim-mock:false}")
  private boolean mock;

  public IsaacSimClient(
      RestTemplate restTemplate,
      @Value("${worker.isaac-sim-base-url}") String baseUrl
  ) {
    this.restTemplate = restTemplate;
    this.baseUrl = baseUrl;
  }

  // match Isaac Sim expected field name: "joint_angles"
  static class IsaacSimRequest {
    @JsonProperty("joint_angles")
    public List<Double> jointAngles;

    public IsaacSimRequest(List<Double> jointAngles) {
      this.jointAngles = jointAngles;
    }
  }

  public SimResponse sendJointAngles(JointAngleMessage msg) {
    if (mock) {
      log.info("→ Isaac Sim [MOCK] returning fake response");
      SimResponse r = new SimResponse();
      r.appliedJoints = Map.of(
          "panda_joint1", 0.1,
          "panda_joint2", -0.3,
          "panda_joint3", 0.0,
          "panda_joint4", -1.5,
          "panda_joint5", 0.0,
          "panda_joint6", 1.8,
          "panda_joint7", 0.7
      );
      r.collision = false;
      r.endEffector = new SimResponse.EndEffector();
      r.endEffector.x = 0.107;
      r.endEffector.y = 0.0;
      r.endEffector.z = 0.927;
      return r;
    }

    String url = baseUrl + UPDATE_PATH;

    HttpHeaders headers = new HttpHeaders();
    headers.setContentType(MediaType.APPLICATION_JSON);

    IsaacSimRequest request = new IsaacSimRequest(msg.jointAngles);

    String effectiveDeviceId =
        (msg.deviceId != null && !msg.deviceId.isBlank()) ? msg.deviceId : msg.robotId;

    log.info("→ Isaac Sim device={} joints={}", effectiveDeviceId, msg.jointAngles);

    ResponseEntity<SimResponse> resp =
        restTemplate.postForEntity(url, new HttpEntity<>(request, headers), SimResponse.class);

    log.info("← Isaac Sim status={}", resp.getStatusCode());
    return resp.getBody();
  }
}