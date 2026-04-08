package registrationservice.controller;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import registrationservice.model.CreateDeviceRequest;
import registrationservice.model.CreateLabRequest;
import registrationservice.model.Device;
import registrationservice.model.Lab;
import registrationservice.model.LabWithDevices;
import registrationservice.service.RegistrationService;

import java.util.List;

@RestController
@RequestMapping("/labs")
public class RegistrationController {

  private final RegistrationService registrationService;

  public RegistrationController(RegistrationService registrationService) {
    this.registrationService = registrationService;
  }

  @PostMapping
  @ResponseStatus(HttpStatus.CREATED)
  public Lab createLab(@RequestBody CreateLabRequest request) {
    return registrationService.createLab(request);
  }

  @GetMapping
  public List<Lab> getAllLabs() {
    return registrationService.getAllLabs();
  }

  @PostMapping("/{labId}/devices")
  @ResponseStatus(HttpStatus.CREATED)
  public Device createDevice(@PathVariable String labId,
      @RequestBody CreateDeviceRequest request) {
    return registrationService.createDevice(labId, request);
  }

  @GetMapping("/{labId}/devices")
  public List<Device> getDevicesByLab(@PathVariable String labId) {
    return registrationService.getDevicesByLab(labId);
  }

  @GetMapping("/{labId}/devices/{deviceId}")
  public Device getDevice(@PathVariable String labId,
      @PathVariable String deviceId) {
    return registrationService.getDevice(labId, deviceId);
  }

  @GetMapping("/full")
  public List<LabWithDevices> getAllLabsWithDevices() {
    return registrationService.getAllLabsWithDevices();
  }
}