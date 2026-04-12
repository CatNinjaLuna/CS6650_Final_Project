package registrationservice.model;

import java.util.List;

public class LabWithDevices {
  private String labId;
  private String name;
  private String location;
  private List<Device> devices;

  public LabWithDevices() {
  }

  public LabWithDevices(String labId, String name, String location, List<Device> devices) {
    this.labId = labId;
    this.name = name;
    this.location = location;
    this.devices = devices;
  }

  public String getLabId() {
    return labId;
  }

  public void setLabId(String labId) {
    this.labId = labId;
  }

  public String getName() {
    return name;
  }

  public void setName(String name) {
    this.name = name;
  }

  public String getLocation() {
    return location;
  }

  public void setLocation(String location) {
    this.location = location;
  }

  public List<Device> getDevices() {
    return devices;
  }

  public void setDevices(List<Device> devices) {
    this.devices = devices;
  }
}