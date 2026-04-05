package worker3;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.http.urlconnection.UrlConnectionHttpClient;
import software.amazon.awssdk.services.sqs.SqsClient;

@Configuration
public class AppConfig {

  @Value("${worker.aws-region:us-east-1}")
  private String awsRegion;

  @Bean
  public SqsClient sqsClient() {
    return SqsClient.builder()
        .region(Region.of(awsRegion))
        .httpClient(UrlConnectionHttpClient.create())
        .build();
  }

  @Bean
  public RestTemplate restTemplate() {
    return new RestTemplate();
  }
}