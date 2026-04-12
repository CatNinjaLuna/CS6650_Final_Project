package worker3;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

@Component
public class RegistrationServiceClient {

  private final RestTemplate restTemplate;
  private final String baseUrl;

  public RegistrationServiceClient(
      RestTemplate restTemplate,
      @Value("${worker.registration-service-base-url}") String baseUrl
  ) {
    this.restTemplate = restTemplate;
    this.baseUrl = baseUrl;
  }

  public boolean deviceExists(String labId, String deviceId) {
    String url = baseUrl + "/labs/" + labId + "/devices/" + deviceId;
    try {
      ResponseEntity<String> response = restTemplate.getForEntity(url, String.class);
      return response.getStatusCode().is2xxSuccessful();
    } catch (Exception e) {
      return false;
    }
  }
}