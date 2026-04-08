package worker3;

import com.fasterxml.jackson.annotation.JsonProperty;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.List;

@Component
public class IsaacSimClient {

  private static final Logger log = LoggerFactory.getLogger(IsaacSimClient.class);
  private static final String UPDATE_PATH = "/roboparam/roboparam/update";

  private final RestTemplate restTemplate;
  private final String baseUrl;

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