package worker3;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.ObjectMapper;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.DeleteMessageRequest;
import software.amazon.awssdk.services.sqs.model.Message;
import software.amazon.awssdk.services.sqs.model.ReceiveMessageRequest;

/**
 * Multithreaded SQS poller.
 *
 * Launches {@code worker.poller-threads} (default 4) dedicated threads, each
 * running a continuous long-poll loop against SQS.  SQS distributes messages
 * across all threads so throughput scales linearly with thread count.
 *
 * Each thread:
 *   1. Long-polls SQS (blocks up to waitTimeSeconds waiting for messages)
 *   2. Processes each message sequentially: Isaac Sim → Redis publish → SQS delete
 *   3. Immediately loops back — no artificial sleep between polls
 */
@Component
public class SqsPoller {

  private static final Logger log = LoggerFactory.getLogger(SqsPoller.class);
  private static final String REDIS_CHANNEL = "roboparam:results";

  private final SqsClient        sqs;
  private final IsaacSimClient   isaacSim;
  private final StringRedisTemplate redis;
  private final ObjectMapper     mapper = new ObjectMapper();

  @Value("${worker.sqs-queue-url}")
  private String queueUrl;

  @Value("${worker.max-messages:10}")
  private int maxMessages;

  @Value("${worker.wait-time-seconds:20}")
  private int waitTime;

  @Value("${worker.poller-threads:4}")
  private int pollerThreads;

  private ExecutorService  pollerExecutor;
  private final AtomicBoolean stopping      = new AtomicBoolean(false);
  private final AtomicInteger pollerCounter = new AtomicInteger(0);

  public SqsPoller(SqsClient sqs, IsaacSimClient isaacSim, StringRedisTemplate redis) {
    this.sqs      = sqs;
    this.isaacSim = isaacSim;
    this.redis    = redis;
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  @PostConstruct
  public void startPollers() {
    pollerExecutor = Executors.newFixedThreadPool(pollerThreads, r -> {
      Thread t = new Thread(r, "sqs-poller-" + pollerCounter.getAndIncrement());
      t.setDaemon(true);
      return t;
    });
    for (int i = 0; i < pollerThreads; i++) {
      pollerExecutor.submit(this::runPollerLoop);
    }
    log.info("Started {} SQS poller threads (maxMessages={}, waitTime={}s)",
        pollerThreads, maxMessages, waitTime);
  }

  @PreDestroy
  public void stopPollers() {
    log.info("Stopping SQS pollers ...");
    stopping.set(true);
    pollerExecutor.shutdownNow();
    try {
      pollerExecutor.awaitTermination(10, TimeUnit.SECONDS);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
    }
    log.info("SQS pollers stopped.");
  }

  // ── Poller loop (one per thread) ───────────────────────────────────────────

  private void runPollerLoop() {
    String threadName = Thread.currentThread().getName();
    log.debug("[{}] Poller started", threadName);

    while (!stopping.get() && !Thread.currentThread().isInterrupted()) {
      try {
        poll();
      } catch (Exception e) {
        if (stopping.get()) break;
        log.error("[{}] Unexpected error: {} — retrying in 1s", threadName, e.getMessage());
        try {
          Thread.sleep(1_000);
        } catch (InterruptedException ie) {
          Thread.currentThread().interrupt();
          break;
        }
      }
    }

    log.debug("[{}] Poller stopped", threadName);
  }

  // ── Single poll-and-process cycle ─────────────────────────────────────────

  /**
   * Long-polls SQS for up to {@code waitTime} seconds, then processes every
   * received message.  Returns immediately if no messages arrive.
   */
  void poll() {
    List<Message> msgs = sqs.receiveMessage(ReceiveMessageRequest.builder()
        .queueUrl(queueUrl)
        .maxNumberOfMessages(maxMessages)
        .waitTimeSeconds(waitTime)
        .build()).messages();

    for (Message m : msgs) {
      processMessage(m);
    }
  }

  // ── Per-message processing ─────────────────────────────────────────────────

  private void processMessage(Message m) {
    try {
      JointAngleMessage payload = mapper.readValue(m.body(), JointAngleMessage.class);

      long start  = System.currentTimeMillis();
      SimResponse result  = isaacSim.sendJointAngles(payload);
      long latency = System.currentTimeMillis() - start;

      // Convert appliedJoints map (panda_joint1..7) → sorted list [j1..j7]
      List<Double> jointList = new ArrayList<>(new TreeMap<>(result.appliedJoints).values());

      // Prefer deviceId, fall back to robotId
      String deviceId = payload.deviceId != null ? payload.deviceId
          : payload.robotId  != null ? payload.robotId
          : "arm-1";

      Map<String, Object> wsPayload = Map.of(
          "deviceId",    deviceId,
          "module",      "kinematics",
          "jointAngles", jointList,
          "endEffector", result.endEffector != null ? result.endEffector : Map.of(),
          "collision",   result.collision,
          "latency",     latency
      );

      redis.convertAndSend(REDIS_CHANNEL, mapper.writeValueAsString(wsPayload));
      log.debug("[{}] Published deviceId={} latency={}ms",
          Thread.currentThread().getName(), deviceId, latency);

      sqs.deleteMessage(DeleteMessageRequest.builder()
          .queueUrl(queueUrl)
          .receiptHandle(m.receiptHandle())
          .build());

    } catch (Exception e) {
      log.error("[{}] Failed msg id={}: {}",
          Thread.currentThread().getName(), m.messageId(), e.getMessage());
    }
  }
}
