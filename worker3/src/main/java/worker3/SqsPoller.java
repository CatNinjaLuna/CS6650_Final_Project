package worker3;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.*;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

@Component
public class SqsPoller {

  private static final Logger log = LoggerFactory.getLogger(SqsPoller.class);
  private static final String REDIS_CHANNEL = "roboparam:results";

  private final SqsClient sqs;
  private final IsaacSimClient isaacSim;
  private final StringRedisTemplate redis;
  private final ObjectMapper mapper = new ObjectMapper();

  @Value("${worker.sqs-queue-url}")
  private String queueUrl;

  @Value("${worker.max-messages:5}")
  private int maxMessages;

  @Value("${worker.wait-time-seconds:20}")
  private int waitTime;

  public SqsPoller(SqsClient sqs, IsaacSimClient isaacSim, StringRedisTemplate redis) {
    this.sqs = sqs;
    this.isaacSim = isaacSim;
    this.redis = redis;
  }

  @Scheduled(fixedDelay = 500)
  public void poll() {
    List<Message> msgs = sqs.receiveMessage(ReceiveMessageRequest.builder()
        .queueUrl(queueUrl)
        .maxNumberOfMessages(maxMessages)
        .waitTimeSeconds(waitTime)
        .build()).messages();

    for (Message m : msgs) {
      try {
        JointAngleMessage payload = mapper.readValue(m.body(), JointAngleMessage.class);

        long start = System.currentTimeMillis();
        SimResponse result = isaacSim.sendJointAngles(payload);
        long latency = System.currentTimeMillis() - start;

        // Convert appliedJoints map (panda_joint1..7) to sorted list [j1, j2, ...]
        List<Double> jointList = new ArrayList<>(new TreeMap<>(result.appliedJoints).values());

        // Resolve deviceId: prefer new deviceId field, fall back to robotId
        String deviceId = payload.deviceId != null ? payload.deviceId
            : payload.robotId  != null ? payload.robotId
                : "arm-1";

        // Build WebSocket payload and publish to aggregator via Redis
        Map<String, Object> wsPayload = Map.of(
            "deviceId",    deviceId,
            "module",      "kinematics",
            "jointAngles", jointList,
            "endEffector", result.endEffector != null ? result.endEffector : Map.of(),
            "collision",   result.collision,
            "latency",     latency
        );
        redis.convertAndSend(REDIS_CHANNEL, mapper.writeValueAsString(wsPayload));
        log.info("Published to Redis: deviceId={} latency={}ms", deviceId, latency);

        sqs.deleteMessage(DeleteMessageRequest.builder()
            .queueUrl(queueUrl)
            .receiptHandle(m.receiptHandle())
            .build());

      } catch (Exception e) {
        log.error("Failed msg id={}: {}", m.messageId(), e.getMessage());
      }
    }
  }
}