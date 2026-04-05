package worker3;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class Worker3 {
  public static void main(String[] args) {
    SpringApplication.run(Worker3.class, args);
  }
}