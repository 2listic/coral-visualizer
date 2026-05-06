import os
import sys

# Add the current directory to sys.path to import paraview_runtime
sys.path.append(os.getcwd())

from paraview import simple


def debug_pvd():
    filename = os.path.abspath("test_data/animation.pvd")
    print(f"Loading file: {filename}")

    source = simple.OpenDataFile(filename)
    if source is None:
        print("Failed to load source")
        return

    source.UpdatePipeline()

    scene = simple.GetAnimationScene()
    scene.UpdateAnimationUsingDataTimeSteps()  # Try to force update

    times = scene.TimeKeeper.TimestepValues
    print(f"TimestepValues: {times}")
    print(f"Current Time: {scene.AnimationTime}")

    if times:
        print(f"Number of timesteps: {len(times)}")
    else:
        # Check source directly
        info = source.GetDataInformation()
        if hasattr(info, "GetTimeSpan"):
            print(f"TimeSpan from Info: {info.GetTimeSpan()}")

        # Check if source has timesteps
        if hasattr(source, "TimestepValues"):
            print(f"Source TimestepValues: {source.TimestepValues}")


if __name__ == "__main__":
    debug_pvd()
