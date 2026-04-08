package worker3;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.*;

import java.util.List;

@Component
public class SqsPoller {

  private static final Logger log = LoggerFactory.getLogger(SqsPoller.class);

  private final SqsClient sqs;
  private final IsaacSimClient isaacSim;
  private final RegistrationServiceClient registrationServiceClient;
  private final ObjectMapper mapper = new ObjectMapper();

  @Value("${worker.sqs-queue-url}")
  private String queueUrl;

  @Value("${worker.max-messages:5}")
  private int maxMessages;

  @Value("${worker.wait-time-seconds:20}")
  private int waitTime;

  public SqsPoller(
      SqsClient sqs,
      IsaacSimClient isaacSim,
      RegistrationServiceClient registrationServiceClient
  ) {
    this.sqs = sqs;
    this.isaacSim = isaacSim;
    this.registrationServiceClient = registrationServiceClient;
  }

  @Scheduled(fixedDelay = 500)
  public void poll() {
    List<Message> msgs = sqs.receiveMessage(
        ReceiveMessageRequest.builder()
            .queueUrl(queueUrl)
            .maxNumberOfMessages(maxMessages)
            .waitTimeSeconds(waitTime)
            .build()
    ).messages();

    for (Message m : msgs) {
      try {
        JointAngleMessage payload = mapper.readValue(m.body(), JointAngleMessage.class);

        String effectiveDeviceId =
            (payload.deviceId != null && !payload.deviceId.isBlank())
                ? payload.deviceId
                : payload.robotId;

        if (payload.labId == null || payload.labId.isBlank()) {
          log.warn("Skipping msg id={} because labId is missing", m.messageId());
          continue;
        }

        if (effectiveDeviceId == null || effectiveDeviceId.isBlank()) {
          log.warn("Skipping msg id={} because deviceId/robotId is missing", m.messageId());
          continue;
        }

        if (!registrationServiceClient.deviceExists(payload.labId, effectiveDeviceId)) {
          log.warn(
              "Skipping msg id={} because device {} does not exist in lab {}",
              m.messageId(),
              effectiveDeviceId,
              payload.labId
          );
          continue;
        }

        // normalize for downstream usage
        payload.deviceId = effectiveDeviceId;

        SimResponse result = isaacSim.sendJointAngles(payload);

        // TODO: forward result to WebSocket aggregator
        log.info("Sim result: {}", mapper.writeValueAsString(result));

        sqs.deleteMessage(
            DeleteMessageRequest.builder()
                .queueUrl(queueUrl)
                .receiptHandle(m.receiptHandle())
                .build()
        );

      } catch (Exception e) {
        log.error("Failed msg id={}: {}", m.messageId(), e.getMessage(), e);
      }
    }
  }
}