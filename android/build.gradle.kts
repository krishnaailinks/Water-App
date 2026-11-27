allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

// Flutter expects the Android outputs under <project>/build rather than
// android/build.
val newBuildDir = rootProject.file("../build")
rootProject.layout.buildDirectory.set(newBuildDir)

subprojects {
    val newSubprojectBuildDir = File(newBuildDir, project.name)
    project.layout.buildDirectory.set(newSubprojectBuildDir)
}

subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
