# Blender Helmet Wig Generator

Blender 4.x add-on for generating 3D-printable helmet wig bases from tape measurements. No scanner needed — just a tape measure and Blender.

Built for cosplayers who want custom-fit wig bases they can print on any FDM printer.

## How It Works

1. **Measure your head** with a tape measure (10 measurements)
2. **Enter measurements** in the Blender panel
3. **Generate** a parametric shell that fits your head
4. **Add vents** for airflow
5. **Export STL** and print in PETG
6. **Finish** with EVA foam liner, straps, and hair

## Measurements Needed

| Measurement | Description |
|---|---|
| Head Circumference | Around the widest part of the head |
| Front-to-Back Arc | Hairline to nape, over the top |
| Ear-to-Ear Arc (over top) | Left ear to right ear, over the crown |
| Ear-to-Ear Arc (around back) | Left ear to right ear, around back |
| Head Width | Side to side, straight line |
| Head Depth | Front to back, straight line |
| Head Height | Ear-top level to crown |
| Forehead Width | Temple to temple |
| Nape Width | Width at base of skull |
| Forehead Height | Hairline to brow ridge |

## Install

### Symlink (development)
```bash
ln -s /path/to/blender-helmet-wig/helmet_wig_base \
  ~/.config/blender/4.0/scripts/addons/helmet_wig_base
```

### Zip (release)
```bash
zip -r helmet_wig_base.zip helmet_wig_base/
```
Then install via Blender → Edit → Preferences → Add-ons → Install.

## Print Settings

- **Material:** PETG (recommended) or PLA+
- **Layer height:** 0.2mm
- **Infill:** Not applicable (it's a shell)
- **Supports:** Minimal, depends on edge cut angle

## Status

🚧 Work in progress. Ported from a LiDAR scan-based pipeline, pivoting to parametric generation from tape measurements.

## License

MIT
