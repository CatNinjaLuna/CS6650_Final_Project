package registrationservice.model;

public class Lab {
  private String labId;
  private String name;
  private String location;

  public Lab() {
  }

  public Lab(String labId, String name, String location) {
    this.labId = labId;
    this.name = name;
    this.location = location;
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
}